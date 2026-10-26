"""Preferencias operativas compartidas entre los dos Cloud Shell.

Firestore es la fuente de verdad cuando hay proyecto configurado. El JSON local
solo se utiliza sin Firestore, y nunca como fallback silencioso ante errores.
No crea/modifica el documento del catálogo de programas y planes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from programas_planes_sync import EdicionDesactualizada, ErrorSincronizacion, proyecto_configurado

LOCAL_PATH = Path(__file__).resolve().parent / "settings" / "operacion_global.json"
COLECCION = "homcloud_config"
DOCUMENTO = "preferencias_operativas"
VERSION = 1
DEFAULTS = {"procesos_predeterminados": 4}


def validar_preferencias(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Las preferencias deben ser un objeto JSON.")
    valor = data.get("procesos_predeterminados", 4)
    if isinstance(valor, bool):
        raise ValueError("El número de procesos debe ser un entero.")
    try:
        numero = int(valor)
    except (TypeError, ValueError) as exc:
        raise ValueError("El número de procesos debe ser un entero.") from exc
    if str(numero) != str(valor).strip() or not 1 <= numero <= 20:
        raise ValueError("Los procesos simultáneos deben estar entre 1 y 20.")
    return {"procesos_predeterminados": numero}


def _cliente_y_doc(proyecto):
    try:
        from google.cloud import firestore
        cliente = firestore.Client(project=proyecto, database="(default)")
        return cliente, cliente.collection(COLECCION).document(DOCUMENTO)
    except Exception as exc:
        raise ErrorSincronizacion(f"No se pudo conectar a Firestore: {exc}") from exc


def leer_preferencias() -> tuple[dict, str | None, str | None]:
    proyecto = proyecto_configurado()
    if not proyecto:
        if not LOCAL_PATH.is_file():
            return DEFAULTS.copy(), None, None
        try:
            return validar_preferencias(json.loads(LOCAL_PATH.read_text(encoding="utf-8"))), None, None
        except (OSError, ValueError, TypeError) as exc:
            raise ErrorSincronizacion(f"Preferencias locales inválidas: {exc}") from exc

    _, doc = _cliente_y_doc(proyecto)
    try:
        snapshot = doc.get(timeout=12)
        if not snapshot.exists:
            return DEFAULTS.copy(), None, proyecto
        data = snapshot.to_dict()
        if not isinstance(data, dict) or data.get("version") != VERSION:
            raise ErrorSincronizacion("Versión de preferencias globales no compatible.")
        return validar_preferencias(data), snapshot.update_time.isoformat(), proyecto
    except ErrorSincronizacion:
        raise
    except Exception as exc:
        raise ErrorSincronizacion(f"No se pudo leer las preferencias globales ({proyecto}): {exc}") from exc


def guardar_preferencias(datos: dict, revision_esperada: str | None) -> dict:
    preferencias = validar_preferencias(datos)
    proyecto = proyecto_configurado()
    if not proyecto:
        LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporal = LOCAL_PATH.with_suffix(".json.tmp")
        temporal.write_text(json.dumps(preferencias, indent=2) + "\n", encoding="utf-8")
        os.replace(temporal, LOCAL_PATH)
        return preferencias

    cliente, doc = _cliente_y_doc(proyecto)
    payload = {
        **preferencias,
        "version": VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        snapshot = doc.get(timeout=12)
        revision_actual = snapshot.update_time.isoformat() if snapshot.exists else None
        if revision_actual != revision_esperada:
            raise EdicionDesactualizada(
                "Otra instancia guardó preferencias nuevas. Recarga la página antes de guardar."
            )
        if snapshot.exists:
            doc.update(payload, option=cliente.write_option(last_update_time=snapshot.update_time), timeout=12)
        else:
            doc.create(payload, timeout=12)
    except EdicionDesactualizada:
        raise
    except Exception as exc:
        try:
            from google.api_core.exceptions import AlreadyExists, FailedPrecondition, Aborted, NotFound
            if isinstance(exc, (AlreadyExists, FailedPrecondition, Aborted, NotFound)):
                raise EdicionDesactualizada(
                    "Las preferencias cambiaron durante el guardado. Recarga y vuelve a intentar."
                ) from exc
        except ImportError:
            pass
        raise ErrorSincronizacion(f"No se guardaron las preferencias en Firestore: {exc}") from exc
    return preferencias
