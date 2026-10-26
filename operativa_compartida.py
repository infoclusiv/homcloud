"""Configuraciones compartidas de homcloud con control de revisiones.

No modifica prompts ni preferencias locales. La primera publicación es manual;
los registros no se generan automáticamente leyendo los dos Cloud Shell.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from configuracion_global import _cliente_y_doc
from programas_planes_sync import EdicionDesactualizada, ErrorSincronizacion, proyecto_configurado

TIPOS = ("prompts", "modelo", "timeouts")
VERSION = 1
_MAX_PROMPT = 30000
_MAX_MODELO = 200


def validar_bloque(tipo: str, valores: dict) -> dict:
    if tipo not in TIPOS:
        raise ValueError("Tipo de configuración no permitido.")
    if not isinstance(valores, dict):
        raise ValueError("La configuración debe ser un objeto.")
    if tipo == "prompts":
        salida = {}
        for nombre in ("pregrado", "posgrado"):
            valor = valores.get(nombre)
            if not isinstance(valor, str) or not valor.strip():
                raise ValueError(f"El prompt de {nombre} no puede estar vacío.")
            if len(valor) > _MAX_PROMPT:
                raise ValueError(f"El prompt de {nombre} excede {_MAX_PROMPT} caracteres.")
            salida[nombre] = valor
        return salida
    if tipo == "modelo":
        valor = valores.get("modelo", "")
        if not isinstance(valor, str) or len(valor) > _MAX_MODELO:
            raise ValueError("El identificador de modelo debe tener 200 caracteres como máximo.")
        valor = valor.strip()
        if any(c in valor for c in ("\r", "\n", "\x00")):
            raise ValueError("El identificador de modelo no puede contener saltos de línea.")
        return {"modelo": valor}
    salida = {}
    for clave, minimo, maximo in (
        ("timeout_opencode_minutos", 5, 45),
        ("timeout_pdf_minutos", 5, 90),
    ):
        numero = valores.get(clave)
        if type(numero) is not int or not minimo <= numero <= maximo:
            raise ValueError(f"{clave} debe ser entero entre {minimo} y {maximo}.")
        salida[clave] = numero
    return salida


def _doc(tipo: str):
    if tipo not in TIPOS:
        raise ValueError("Tipo de configuración no permitido.")
    proyecto = proyecto_configurado()
    if not proyecto:
        return None, None, None
    cliente, doc = _cliente_y_doc(proyecto)
    return cliente, cliente.collection("homcloud_config").document(f"{tipo}_compartidos"), proyecto


def _desde_snapshot(tipo: str, snapshot):
    if not snapshot.exists:
        return None, None
    data = snapshot.to_dict()
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise ErrorSincronizacion(f"Versión no reconocida en configuración global de {tipo}.")
    try:
        contenido = validar_bloque(tipo, data.get("contenido"))
    except ValueError as exc:
        raise ErrorSincronizacion(f"Configuración global de {tipo} inválida: {exc}") from exc
    return contenido, snapshot.update_time.isoformat()


def leer_bloque(tipo: str) -> tuple[dict | None, str | None, str | None]:
    """None significa aún no publicado, NO usar defaults ocultos en Firestore."""
    _, doc, proyecto = _doc(tipo)
    if not proyecto:
        return None, None, None
    try:
        contenido, revision = _desde_snapshot(tipo, doc.get(timeout=12))
        return contenido, revision, proyecto
    except ErrorSincronizacion:
        raise
    except Exception as exc:
        raise ErrorSincronizacion(
            f"No se pudo leer la configuración global de {tipo} ({proyecto}): {exc}"
        ) from exc


def guardar_bloque(tipo: str, valores: dict, revision_esperada: str | None) -> dict:
    contenido = validar_bloque(tipo, valores)
    cliente, doc, proyecto = _doc(tipo)
    if not proyecto:
        raise ErrorSincronizacion("Firestore no está configurado; utiliza el guardado local.")
    payload = {
        "version": VERSION,
        "contenido": contenido,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        snapshot = doc.get(timeout=12)
        _, revision_actual = _desde_snapshot(tipo, snapshot)
        if revision_actual != revision_esperada:
            raise EdicionDesactualizada(
                f"Se ha editado {tipo} desde otro Cloud Shell. "
                "Recarga la configuración compartida antes de publicar."
            )
        if not snapshot.exists:
            # Create exclusiva, incluso si dos usuarios publican simultáneamente.
            doc.create(payload, timeout=12)
        else:
            # Conservar versiones anteriores en Firestore con la escritura nueva.
            batch = cliente.batch()
            anterior = snapshot.to_dict()
            historial = doc.collection("historial").document()
            batch.set(historial, {
                "version": VERSION,
                "contenido": anterior["contenido"],
                "revision_origen": revision_actual,
                "archived_at": datetime.now(timezone.utc).isoformat(),
            })
            batch.update(doc, payload, option=cliente.write_option(last_update_time=snapshot.update_time))
            batch.commit()
    except EdicionDesactualizada:
        raise
    except ErrorSincronizacion:
        raise
    except Exception as exc:
        try:
            from google.api_core.exceptions import (
                AlreadyExists, Conflict, FailedPrecondition, Aborted, NotFound,
            )
            if isinstance(exc, (AlreadyExists, Conflict, FailedPrecondition, Aborted, NotFound)):
                raise EdicionDesactualizada(
                    f"{tipo} cambió durante la publicación. Recarga y vuelve a intentar."
                ) from exc
        except ImportError:
            pass
        raise ErrorSincronizacion(f"No se pudo publicar {tipo} en Firestore: {exc}") from exc
    return contenido


def listar_historial(tipo: str, limite: int = 10) -> list[dict]:
    """Metadatos limitados; solo obtiene contenidos al restaurar explícitamente."""
    _, doc, proyecto = _doc(tipo)
    if not proyecto:
        return []
    try:
        results = doc.collection("historial").order_by("archived_at", direction="DESCENDING").limit(
            max(1, min(int(limite), 30))
        ).stream(timeout=12)
        return [
            {"id": snapshot.id, "archived_at": (snapshot.to_dict() or {}).get("archived_at", "")}
            for snapshot in results
        ]
    except Exception as exc:
        raise ErrorSincronizacion(f"No se pudo consultar el historial de {tipo}: {exc}") from exc


def restaurar_historial(tipo: str, version_id: str, revision_esperada: str | None) -> dict:
    """Restaurar deja también un registro de la versión reemplazada."""
    if not isinstance(version_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,128}", version_id):
        raise ValueError("Identificador de versión inválido.")
    _, doc, proyecto = _doc(tipo)
    if not proyecto:
        raise ErrorSincronizacion("Firestore no está configurado.")
    try:
        snapshot = doc.collection("historial").document(version_id).get(timeout=12)
        if not snapshot.exists:
            raise ValueError("La versión seleccionada ya no existe.")
        contenido = validar_bloque(tipo, snapshot.to_dict().get("contenido"))
    except (ErrorSincronizacion, ValueError):
        raise
    except Exception as exc:
        raise ErrorSincronizacion(f"No se pudo leer la versión histórica: {exc}") from exc
    return guardar_bloque(tipo, contenido, revision_esperada)
