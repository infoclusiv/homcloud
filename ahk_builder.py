from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any


AHK_HEADER = """#SingleInstance force
#NoEnv
SendMode Input
SetKeyDelay, 10  ; Aumenta el tiempo entre teclas (en milisegundos)
; ===== ESPERAR Y ACTIVAR LA VENTANA ESPECÍFICA =====
WinTitle := "Oracle Fusion Middleware Forms Services:  Open > SHATRNS"
; Esperar hasta que la ventana exista
WinWait, %WinTitle%
; Activar la ventana objetivo
WinActivate, %WinTitle%
WinWaitActive, %WinTitle%
"""


class AhkBuilderError(ValueError):
    pass


def extraer_json_desde_respuesta(respuesta: str) -> dict[str, Any]:
    """
    Extrae un objeto JSON desde la respuesta del modelo.
    Acepta:
    - JSON puro
    - JSON dentro de ```json ... ```
    - Texto con un único bloque JSON embebido
    """
    if not respuesta or not respuesta.strip():
        raise AhkBuilderError("La respuesta de OpenCode está vacía.")

    texto = respuesta.strip()

    texto = re.sub(r"^```(?:json)?\s*", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s*```$", "", texto)

    try:
        data = json.loads(texto)
    except json.JSONDecodeError:
        inicio = texto.find("{")
        fin = texto.rfind("}")

        if inicio == -1 or fin == -1 or fin <= inicio:
            raise AhkBuilderError("No se encontró un objeto JSON válido en la respuesta.")

        bloque = texto[inicio : fin + 1]

        try:
            data = json.loads(bloque)
        except json.JSONDecodeError as e:
            raise AhkBuilderError(f"JSON inválido: {e}") from e

    if not isinstance(data, dict):
        raise AhkBuilderError("El JSON principal debe ser un objeto.")

    return data


def limpiar_letras(valor: Any) -> str:
    texto = str(valor or "").upper()
    texto = re.sub(r"[^A-ZÑ]", "", texto)
    return texto


def limpiar_numeros(valor: Any) -> str:
    texto = str(valor or "").upper()
    texto = texto.replace(" ", "")
    texto = re.sub(r"[^0-9]", "", texto)
    return texto


def formatear_calificacion(valor: Any) -> str:
    texto = str(valor or "").strip().replace(",", ".")

    if not texto:
        raise AhkBuilderError("Calificación vacía.")

    try:
        numero = Decimal(texto)
    except InvalidOperation as e:
        raise AhkBuilderError(f"Calificación inválida: {valor}") from e

    return f"{numero:.2f}"


def separar_codigo_original(codigo_original: Any) -> tuple[str, str]:
    """
    Fallback cuando el JSON no trae letras/numeros separados.
    Conserva todos los dígitos y todas las letras del código.
    """
    codigo = str(codigo_original or "").upper().replace(" ", "")

    letras = limpiar_letras(codigo)
    numeros = limpiar_numeros(codigo)

    return letras, numeros


def normalizar_registro(registro: dict[str, Any], indice: int) -> dict[str, str]:
    if not isinstance(registro, dict):
        raise AhkBuilderError(f"El registro #{indice} no es un objeto JSON.")

    letras = limpiar_letras(registro.get("letras"))
    numeros = limpiar_numeros(registro.get("numeros"))

    if not letras or not numeros:
        letras_fallback, numeros_fallback = separar_codigo_original(
            registro.get("codigo_original") or registro.get("codigo")
        )
        letras = letras or letras_fallback
        numeros = numeros or numeros_fallback

    if not letras:
        raise AhkBuilderError(f"El registro #{indice} no tiene letras de código.")

    if not numeros:
        raise AhkBuilderError(f"El registro #{indice} no tiene números de código.")

    calificacion = formatear_calificacion(registro.get("calificacion"))

    return {
        "letras": letras,
        "numeros": numeros,
        "calificacion": calificacion,
    }


def generar_script_ahk_desde_registros(registros: list[dict[str, Any]]) -> str:
    if not isinstance(registros, list) or not registros:
        raise AhkBuilderError("No hay registros para generar el AHK.")

    registros_limpios = [
        normalizar_registro(registro, index)
        for index, registro in enumerate(registros, start=1)
    ]

    lineas = [AHK_HEADER.rstrip(), ""]

    total = len(registros_limpios)

    for index, registro in enumerate(registros_limpios, start=1):
        letras = registro["letras"]
        numeros = registro["numeros"]
        calificacion = registro["calificacion"]

        if index == total:
            linea = f"Send, {letras}{{Tab}}{numeros}{{Tab}}{{Tab}}{calificacion}{{Tab}}P"
        else:
            linea = f"Send, {letras}{{Tab}}{numeros}{{Tab}}{{Tab}}{calificacion}{{Tab}}P{{Down}}{{Space}}{{Tab}}"

        lineas.append(linea)

    return "\n".join(lineas).strip() + "\n"


def validar_payload_opencode(data: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    """
    Devuelve:
    estado, motivo_detencion, registros
    """
    estado = str(data.get("estado") or "").strip().lower()
    motivo = str(data.get("motivo_detencion") or "").strip()
    registros = data.get("registros") or []

    if estado not in {"ok", "detenido"}:
        raise AhkBuilderError("El campo 'estado' debe ser 'ok' o 'detenido'.")

    if estado == "detenido":
        return estado, motivo or "OpenCode detuvo la ejecución.", []

    if not isinstance(registros, list) or not registros:
        raise AhkBuilderError("Estado 'ok', pero no hay registros para generar AHK.")

    return estado, motivo, registros


def generar_ahk_desde_respuesta_json(respuesta: str) -> tuple[str, dict[str, Any]]:
    """
    Recibe la respuesta textual de OpenCode.
    Retorna:
    - script AHK generado por Python
    - payload JSON parseado
    """
    data = extraer_json_desde_respuesta(respuesta)
    estado, motivo, registros = validar_payload_opencode(data)

    if estado == "detenido":
        raise AhkBuilderError(motivo)

    script = generar_script_ahk_desde_registros(registros)

    return script, data


def _self_test() -> None:
    respuesta = """
{
  "estado": "ok",
  "motivo_detencion": "",
  "estudiante": "BLANCA NIDIA NUPAN MAMIAN",
  "programa_aspira": "MAESTRIA EN EDUCACIÓN",
  "periodo_academico": "202653",
  "registros": [
    {
      "codigo_original": "MEDR22180",
      "letras": "MEDR",
      "numeros": "22180",
      "calificacion": "4.5"
    },
    {
      "codigo_original": "MEDR22280",
      "letras": "MEDR",
      "numeros": "22280",
      "calificacion": "4.2"
    }
  ]
}
"""

    script, data = generar_ahk_desde_respuesta_json(respuesta)

    assert data["estado"] == "ok"
    assert script.startswith("#SingleInstance force")
    assert "Send, MEDR{Tab}22180{Tab}{Tab}4.50{Tab}P{Down}{Space}{Tab}" in script
    assert "Send, MEDR{Tab}22280{Tab}{Tab}4.20{Tab}P" in script
    assert not script.rstrip().endswith("{Down}{Space}{Tab}")

    print("✅ Self-test OK")
    print()
    print(script)


if __name__ == "__main__":
    _self_test()
