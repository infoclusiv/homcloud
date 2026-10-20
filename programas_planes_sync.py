"""Catálogo de programas/planes compartido entre Cloud Shell mediante Firestore.

Sin configurar settings/cloud_sync.json ni HOMCLOUD_FIRESTORE_PROJECT,
homcloud sigue en modo local. NO se inicializa Firestore automáticamente:
el primer documento solo puede crearse con el comando explícito de bootstrap
ejecutado en el Cloud Shell primario (infoclusiv).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
from uuid import uuid4

from programas_planes import (
    PROGRAMAS_PLANES_CONFIG_VERSION,
    cargar_programas_planes,
    guardar_programas_planes,
    migrar_programas_planes,
    validar_programas_planes,
)

CONFIG_FILE = Path(__file__).resolve().parent / "settings" / "cloud_sync.json"
LOCAL_FILE = Path(__file__).resolve().parent / "settings" / "programas_planes.json"
DOCUMENT_PATH = ("homcloud_config", "programas_planes")
PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


class ErrorSincronizacion(RuntimeError):
    """No se pueden recuperar datos remotos con garantías."""


class NoInicializado(ErrorSincronizacion):
    """Firestore aún no tiene la configuración inicial."""


class EdicionDesactualizada(ErrorSincronizacion):
    """Otra instancia guardó cambios desde que se abrió el editor."""


def proyecto_configurado() -> str | None:
    """Configuración local sin credenciales; variable de entorno tiene prioridad."""
    value = os.environ.get("HOMCLOUD_FIRESTORE_PROJECT", "").strip()
    if not value and CONFIG_FILE.is_file():
        try:
            value = str(json.loads(CONFIG_FILE.read_text(encoding="utf-8"))["project_id"]).strip()
        except (ValueError, TypeError, KeyError) as exc:
            raise ErrorSincronizacion("settings/cloud_sync.json no tiene un project_id válido.") from exc
    if value and not PROJECT_RE.fullmatch(value):
        raise ErrorSincronizacion("El identificador del proyecto Firestore no es válido.")
    return value or None


def _conectar():
    proyecto = proyecto_configurado()
    if not proyecto:
        raise ErrorSincronizacion("Primero configura el proyecto Firestore.")
    try:
        from google.cloud import firestore
    except ImportError as exc:
        raise ErrorSincronizacion(
            "Falta google-cloud-firestore. Ejecuta: python -m pip install -r requirements-sync.txt"
        ) from exc
    try:
        cliente = firestore.Client(project=proyecto, database="(default)")
        doc = cliente.collection(DOCUMENT_PATH[0]).document(DOCUMENT_PATH[1])
        return cliente, doc
    except Exception as exc:
        raise ErrorSincronizacion(f"No se pudo iniciar Firestore: {exc}") from exc


def _extraer_documento(snapshot):
    if not snapshot.exists:
        raise NoInicializado(
            "Firestore todavía no tiene programas/planes. Inicialízalo SOLO desde "
            "Cloud Shell infoclusiv siguiendo SINCRONIZACION_PLANES.md."
        )
    data = snapshot.to_dict()
    if not isinstance(data, dict) or data.get("version") != PROGRAMAS_PLANES_CONFIG_VERSION:
        raise ErrorSincronizacion(
            "Versión o formato del catálogo remoto no reconocidos; no se usarán datos locales por error."
        )
    if not isinstance(data.get("programas"), list) or not data["programas"]:
        raise ErrorSincronizacion("El catálogo remoto está vacío o corrupto.")
    try:
        filas = validar_programas_planes(data["programas"])
    except (ValueError, TypeError) as exc:
        raise ErrorSincronizacion(f"Catálogo remoto inválido: {exc}") from exc
    return filas, snapshot.update_time.isoformat()


def leer_configuracion(path: Path = LOCAL_FILE):
    """Devuelve (filas, revisión, proyecto), con revisión None en modo local.

    Si Firestore falla, NUNCA se reemplaza silenciosamente por el catálogo local.
    """
    proyecto = proyecto_configurado()
    if not proyecto:
        return cargar_programas_planes(path), None, None
    _, doc = _conectar()
    try:
        snapshot = doc.get(timeout=12)
        filas, revision = _extraer_documento(snapshot)
        return filas, revision, proyecto
    except (NoInicializado, ErrorSincronizacion):
        raise
    except Exception as exc:
        raise ErrorSincronizacion(
            f"No se pudo leer Firestore ({proyecto}): {exc}. "
            "Se bloqueó la edición para no sobrescribir datos."
        ) from exc


def _respaldar_local(path: Path):
    if path.is_file():
        carpeta = path.parent / "backups"
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / (
            f"programas_planes-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{uuid4().hex[:8]}.json"
        )
        shutil.copy2(path, destino)
        return destino
    return None


def guardar_configuracion(datos, path: Path = LOCAL_FILE, revision_esperada=None):
    """Guarda con compare-and-swap remoto y respaldo atómico de versión anterior.

    En modo compartido se requiere la revisión del momento de abrir el editor;
    otro guardado (incluso de otro Cloud Shell) causa conflicto, no sobreescritura.
    """
    filas = validar_programas_planes(datos)
    proyecto = proyecto_configurado()
    if not proyecto:
        _respaldar_local(path)
        return guardar_programas_planes(filas, path)
    if not revision_esperada:
        raise EdicionDesactualizada("Falta la revisión inicial del editor: recarga antes de guardar.")
    cliente, doc = _conectar()
    try:
        snapshot = doc.get(timeout=12)
        anterior, revision_actual = _extraer_documento(snapshot)
        if revision_esperada != revision_actual:
            raise EdicionDesactualizada(
                "Los programas/planes cambiaron en otro Cloud Shell. "
                "Recarga desde la nube, revisa y vuelve a aplicar tus cambios."
            )
        # Se respalda primero el JSON local; la copia anterior remota se guarda
        # EN LA MISMA transacción atómica de escritura (batch).
        _respaldar_local(path)
        batch = cliente.batch()
        historia = doc.collection("historial").document(uuid4().hex)
        batch.set(historia, {
            "version": PROGRAMAS_PLANES_CONFIG_VERSION,
            "programas": anterior,
            "revision_origen": revision_actual,
            "archived_at": datetime.now(timezone.utc).isoformat(),
        })
        batch.update(doc, {
            "version": PROGRAMAS_PLANES_CONFIG_VERSION,
            "programas": filas,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, option=cliente.write_option(last_update_time=snapshot.update_time))
        batch.commit()
    except EdicionDesactualizada:
        raise
    except (NoInicializado, ErrorSincronizacion):
        raise
    except Exception as exc:
        # Firestore rechaza la operación si cambió la revisión entre get y commit.
        try:
            from google.api_core.exceptions import FailedPrecondition, NotFound, Aborted
            if isinstance(exc, (FailedPrecondition, NotFound, Aborted)):
                raise EdicionDesactualizada(
                    "El catálogo cambió mientras guardabas. Recarga los datos y vuelve a intentar."
                ) from exc
        except ImportError:
            pass
        raise ErrorSincronizacion(f"No se confirmó el guardado en Firestore: {exc}") from exc
    # El éxito se determinó exclusivamente por Firestore; la copia local es auxiliar.
    try:
        guardar_programas_planes(filas, path)
    except OSError:
        pass
    return filas


def _leer_origen_seguro(path: Path):
    """El bootstrap nunca usa predeterminados silenciosos si falta el JSON."""
    if not path.is_file():
        raise ErrorSincronizacion(
            f"No existe {path}. Abre la app en infoclusiv, verifica y guarda el catálogo "
            "local ANTES de inicializar Firestore."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version = int(data.get("version", 0)) if isinstance(data, dict) else 0
        items = data.get("programas") if isinstance(data, dict) else data
        if not isinstance(items, list) or not items:
            raise ValueError("Faltan programas.")
        filas = (
            validar_programas_planes(items)
            if version >= PROGRAMAS_PLANES_CONFIG_VERSION
            else migrar_programas_planes(items)
        )
        if not filas:
            raise ValueError("Catálogo sin registros.")
        return filas
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ErrorSincronizacion(f"Archivo principal inválido: {exc}") from exc


def inicializar_desde_infoclusiv(path: Path = LOCAL_FILE):
    """Primera carga EXPLÍCITA. doc.create falla si alguien ya lo creó."""
    filas = _leer_origen_seguro(path)
    _respaldar_local(path)
    _, doc = _conectar()
    try:
        doc.create({
            "version": PROGRAMAS_PLANES_CONFIG_VERSION,
            "programas": filas,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "origen_inicial": "infoclusiv",
        })
    except Exception as exc:
        from google.api_core.exceptions import Conflict, AlreadyExists
        if isinstance(exc, (Conflict, AlreadyExists)):
            raise ErrorSincronizacion(
                "La configuración central YA EXISTE: no se reemplazó ningún dato. "
                "Contacta antes de intentar otra importación."
            ) from exc
        raise ErrorSincronizacion(f"No se pudo inicializar Firestore: {exc}") from exc
    return filas


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sincronización global programas/planes")
    sub = parser.add_subparsers(dest="accion", required=True)
    configurar = sub.add_parser("configurar", help="Configurar este Cloud Shell (sin secretos)")
    configurar.add_argument("--project", required=True, help="ID del proyecto de Firestore compartido")
    sub.add_parser("estado", help="Leer estado del catálogo sin modificarlo")
    inicializar = sub.add_parser("inicializar", help="Solo desde infoclusiv")
    inicializar.add_argument("--confirmar-origen-infoclusiv", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.accion == "configurar":
            if not PROJECT_RE.fullmatch(args.project):
                raise ErrorSincronizacion("ID del proyecto inválido.")
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(
                json.dumps({"project_id": args.project}, indent=2) + "\n", encoding="utf-8"
            )
            print(f"Proyecto configurado en este Cloud Shell: {args.project}")
        elif args.accion == "estado":
            filas, revision, proyecto = leer_configuracion()
            print(f"Modo: {'Firestore ' + proyecto if proyecto else 'local'}")
            print(f"Programas: {len(filas)}")
            print(f"Revisión: {revision or 'archivo local'}")
        else:
            if not args.confirmar_origen_infoclusiv:
                raise ErrorSincronizacion(
                    "Rechazado: ejecuta solo en el Cloud Shell infoclusiv "
                    "con --confirmar-origen-infoclusiv."
                )
            filas = inicializar_desde_infoclusiv()
            print(f"Inicialización completa desde infoclusiv: {len(filas)} programas.")
    except ErrorSincronizacion as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
