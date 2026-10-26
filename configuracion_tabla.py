"""Preferencias persistentes de la vista de resultados (NO cambia los CSV).

Sin credenciales nuevas. Comparte la misma configuración Firestore que ya
utilizan los dos Cloud Shell; si no se configuró Firestore, utiliza un JSON local.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from configuracion_global import _cliente_y_doc
from programas_planes_sync import EdicionDesactualizada, ErrorSincronizacion, proyecto_configurado

COLECCION = "homcloud_config"
DOCUMENTO = "columnas_resumen"
ARCHIVO_LOCAL = Path(__file__).resolve().parent / "settings" / "columnas_resumen.json"
VERSION = 1

ORDEN_PREDETERMINADO = (
    "Archivo", "Prompt usado", "Programa origen",
    "Programa al que aspira", "Plan", "Nivel", "Estado", "Error",
    "Créditos homologados", "Duración", "Fase actual", "Worker dir",
    "Modelo OpenCode", "Timeout OpenCode", "Nombre",
    "TXT LLMWhisperer", "Respuesta OpenCode", "Archivo AHK",
)


def validar_orden(orden) -> list[str]:
    if not isinstance(orden, list):
        raise ValueError("El orden de columnas debe ser una lista.")
    if (len(orden) != len(ORDEN_PREDETERMINADO)
            or set(orden) != set(ORDEN_PREDETERMINADO)
            or any(type(col) is not str for col in orden)):
        raise ValueError("El orden debe incluir todas las columnas, exactamente una vez.")
    return list(orden)


def ordenar_visibles(disponibles, orden=None) -> list[str]:
    """Mostrar todas las columnas, incluyendo nuevas incorporadas a futuro."""
    actuales = list(dict.fromkeys(str(col) for col in disponibles))
    preferidas = tuple(orden) if orden is not None else ORDEN_PREDETERMINADO
    resultado = [col for col in preferidas if col in actuales]
    resultado.extend(col for col in actuales if col not in resultado)
    return resultado


def mover_columna(orden: list[str], nombre: str, movimiento: str) -> list[str]:
    columnas = validar_orden(orden)
    if nombre not in columnas or movimiento not in ("izquierda", "derecha", "inicio"):
        raise ValueError("Movimiento de columna no permitido.")
    posicion = columnas.index(nombre)
    if movimiento == "inicio":
        nuevo_indice = 0
    elif movimiento == "izquierda":
        nuevo_indice = max(0, posicion - 1)
    else:
        nuevo_indice = min(len(columnas) - 1, posicion + 1)
    columnas.pop(posicion)
    columnas.insert(nuevo_indice, nombre)
    return columnas


def leer_orden() -> tuple[list[str], str | None, str | None]:
    proyecto = proyecto_configurado()
    if not proyecto:
        if not ARCHIVO_LOCAL.is_file():
            return list(ORDEN_PREDETERMINADO), None, None
        try:
            contenido = json.loads(ARCHIVO_LOCAL.read_text(encoding="utf-8"))
            if not isinstance(contenido, dict) or contenido.get("version") != VERSION:
                raise ValueError("Versión local inválida.")
            return validar_orden(contenido["orden"]), None, None
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            raise ErrorSincronizacion(f"Error leyendo disposición local de columnas: {exc}") from exc

    _, doc = _cliente_y_doc(proyecto)
    try:
        snapshot = doc.get(timeout=12)
        if not snapshot.exists:
            return list(ORDEN_PREDETERMINADO), None, proyecto
        contenido = snapshot.to_dict()
        if not isinstance(contenido, dict) or contenido.get("version") != VERSION:
            raise ErrorSincronizacion("Versión de disposición de columnas no compatible.")
        try:
            orden = validar_orden(contenido.get("orden"))
        except ValueError as exc:
            raise ErrorSincronizacion(f"Disposición de columnas inválida: {exc}") from exc
        return orden, snapshot.update_time.isoformat(), proyecto
    except ErrorSincronizacion:
        raise
    except Exception as exc:
        raise ErrorSincronizacion(f"No se pudo leer el orden global de columnas: {exc}") from exc


def guardar_orden(orden, revision_esperada: str | None) -> list[str]:
    nuevo = validar_orden(orden)
    proyecto = proyecto_configurado()
    if not proyecto:
        ARCHIVO_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        temporal = ARCHIVO_LOCAL.with_suffix(".json.tmp")
        try:
            temporal.write_text(
                json.dumps({"version": VERSION, "orden": nuevo}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporal, ARCHIVO_LOCAL)
        finally:
            temporal.unlink(missing_ok=True)
        return nuevo

    cliente, doc = _cliente_y_doc(proyecto)
    try:
        actual = doc.get(timeout=12)
        revision_actual = actual.update_time.isoformat() if actual.exists else None
        if revision_actual != revision_esperada:
            raise EdicionDesactualizada(
                "El orden se modificó desde el otro Cloud Shell. Actualiza los resultados antes de guardar."
            )
        payload = {"version": VERSION, "orden": nuevo}
        if actual.exists:
            doc.update(payload, option=cliente.write_option(last_update_time=actual.update_time), timeout=12)
        else:
            doc.create(payload, timeout=12)
    except EdicionDesactualizada:
        raise
    except Exception as exc:
        try:
            from google.api_core.exceptions import (
                AlreadyExists, Conflict, FailedPrecondition, Aborted, NotFound,
            )
            if isinstance(exc, (AlreadyExists, Conflict, FailedPrecondition, Aborted, NotFound)):
                raise EdicionDesactualizada(
                    "El orden cambió durante el guardado. Recarga y vuelve a intentar."
                ) from exc
        except ImportError:
            pass
        raise ErrorSincronizacion(f"No se pudo guardar el orden global de columnas: {exc}") from exc
    return nuevo
