from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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


def normalizar_nivel_academico(nivel_academico: Any) -> str:
    """
    Normaliza el nivel académico a uno de estos valores:
    - Pregrado
    - Posgrado

    También acepta:
    - N => Pregrado
    - P => Posgrado
    - Postgrado => Posgrado
    """
    texto = str(nivel_academico or "").strip().lower()

    if not texto:
        raise AhkBuilderError(
            "No se recibió nivel académico. "
            "Debes enviar 'Pregrado' o 'Posgrado' al generar el AHK."
        )

    texto = (
        texto.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )

    if texto in {"pregrado", "pre", "n", "normal"}:
        return "Pregrado"

    if texto in {"posgrado", "postgrado", "post", "p"}:
        return "Posgrado"

    raise AhkBuilderError(
        f"Nivel académico inválido: {nivel_academico!r}. "
        "Valores permitidos: 'Pregrado' o 'Posgrado'."
    )


def obtener_letra_homologacion(nivel_academico: Any) -> str:
    nivel = normalizar_nivel_academico(nivel_academico)

    if nivel == "Pregrado":
        return "N"

    if nivel == "Posgrado":
        return "P"

    raise AhkBuilderError(f"Nivel académico no soportado: {nivel!r}")


def obtener_decimales_calificacion(nivel_academico: Any) -> int:
    nivel = normalizar_nivel_academico(nivel_academico)

    if nivel == "Pregrado":
        return 1

    if nivel == "Posgrado":
        return 2

    raise AhkBuilderError(f"Nivel académico no soportado: {nivel!r}")


def formatear_calificacion(valor: Any, nivel_academico: Any) -> str:
    """
    Formatea la calificación según el nivel académico:

    - Pregrado: 1 decimal
      Ejemplos: 4 -> 4.0, 4.15 -> 4.2, 3.5 -> 3.5

    - Posgrado: 2 decimales
      Ejemplos: 4 -> 4.00, 4.2 -> 4.20, 3.5 -> 3.50
    """
    texto = str(valor or "").strip().replace(",", ".")

    if not texto:
        raise AhkBuilderError("Calificación vacía.")

    try:
        numero = Decimal(texto)
    except InvalidOperation as e:
        raise AhkBuilderError(f"Calificación inválida: {valor}") from e

    decimales = obtener_decimales_calificacion(nivel_academico)

    if decimales == 1:
        numero_formateado = numero.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        return f"{numero_formateado:.1f}"

    if decimales == 2:
        numero_formateado = numero.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{numero_formateado:.2f}"

    raise AhkBuilderError(f"Cantidad de decimales no soportada: {decimales}")


def separar_codigo_original(codigo_original: Any) -> tuple[str, str]:
    """
    Fallback cuando el JSON no trae letras/numeros separados.
    Conserva todos los dígitos y todas las letras del código.
    """
    codigo = str(codigo_original or "").upper().replace(" ", "")

    letras = limpiar_letras(codigo)
    numeros = limpiar_numeros(codigo)

    return letras, numeros


def normalizar_registro(
    registro: dict[str, Any],
    indice: int,
    nivel_academico: Any,
) -> dict[str, str]:
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

    calificacion = formatear_calificacion(
        registro.get("calificacion"),
        nivel_academico=nivel_academico,
    )

    return {
        "letras": letras,
        "numeros": numeros,
        "calificacion": calificacion,
    }


def generar_script_ahk_desde_registros(
    registros: list[dict[str, Any]],
    nivel_academico: Any = None,
) -> str:
    """
    Genera el script AHK final desde los registros JSON.

    Parámetro obligatorio:
    - nivel_academico:
      - 'Pregrado' => usa letra N y calificaciones con 1 decimal.
      - 'Posgrado' => usa letra P y calificaciones con 2 decimales.

    Nota:
    Se deja como parámetro con default None para mostrar un error claro
    si la app llama esta función sin enviar el nivel.
    """
    nivel = normalizar_nivel_academico(nivel_academico)
    letra_homologacion = obtener_letra_homologacion(nivel)

    if not isinstance(registros, list) or not registros:
        raise AhkBuilderError("No hay registros para generar el AHK.")

    registros_limpios = [
        normalizar_registro(
            registro=registro,
            indice=index,
            nivel_academico=nivel,
        )
        for index, registro in enumerate(registros, start=1)
    ]

    lineas = [AHK_HEADER.rstrip(), ""]

    total = len(registros_limpios)

    for index, registro in enumerate(registros_limpios, start=1):
        letras = registro["letras"]
        numeros = registro["numeros"]
        calificacion = registro["calificacion"]

        if index == total:
            linea = (
                f"Send, {letras}{{Tab}}{numeros}{{Tab}}{{Tab}}"
                f"{calificacion}{{Tab}}{letra_homologacion}"
            )
        else:
            linea = (
                f"Send, {letras}{{Tab}}{numeros}{{Tab}}{{Tab}}"
                f"{calificacion}{{Tab}}{letra_homologacion}{{Down}}{{Space}}{{Tab}}"
            )

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


def inferir_nivel_desde_payload(data: dict[str, Any]) -> str | None:
    """
    Fallback opcional para usos directos del builder con el payload completo.

    La app principal debe preferir pasar nivel_academico explícitamente,
    porque esa decisión ya se tomó antes de generar el AHK.
    """
    candidatos = [
        data.get("nivel_academico"),
        data.get("nivel"),
        data.get("tipo_programa"),
    ]

    for candidato in candidatos:
        if candidato:
            try:
                return normalizar_nivel_academico(candidato)
            except AhkBuilderError:
                pass

    programa = str(
        data.get("programa_aspira")
        or data.get("programa_al_que_aspira")
        or ""
    ).lower()

    programa_normalizado = (
        programa.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )

    palabras_posgrado = (
        "maestria",
        "especializacion",
        "posgrado",
        "postgrado",
        "doctorado",
        "master",
        "magister",
        "mba",
    )

    if any(palabra in programa_normalizado for palabra in palabras_posgrado):
        return "Posgrado"

    return None


def generar_ahk_desde_respuesta_json(
    respuesta: str,
    nivel_academico: Any = None,
) -> tuple[str, dict[str, Any]]:
    """
    Recibe la respuesta textual de OpenCode.
    Retorna:
    - script AHK generado por Python
    - payload JSON parseado

    Recomendado:
    - Pasar nivel_academico explícitamente desde la app:
      generar_ahk_desde_respuesta_json(respuesta, nivel_academico="Pregrado")
      generar_ahk_desde_respuesta_json(respuesta, nivel_academico="Posgrado")
    """
    data = extraer_json_desde_respuesta(respuesta)
    estado, motivo, registros = validar_payload_opencode(data)

    if estado == "detenido":
        raise AhkBuilderError(motivo)

    nivel = nivel_academico or inferir_nivel_desde_payload(data)

    if not nivel:
        raise AhkBuilderError(
            "No se pudo determinar el nivel académico para generar el AHK. "
            "Envía nivel_academico='Pregrado' o nivel_academico='Posgrado'."
        )

    script = generar_script_ahk_desde_registros(
        registros,
        nivel_academico=nivel,
    )

    return script, data


def _self_test() -> None:
    registros = [
        {
            "codigo_original": "MEDR22180",
            "letras": "MEDR",
            "numeros": "22180",
            "calificacion": "4.15",
        },
        {
            "codigo_original": "MEDR22280",
            "letras": "MEDR",
            "numeros": "22280",
            "calificacion": "4.2",
        },
    ]

    script_pregrado = generar_script_ahk_desde_registros(
        registros,
        nivel_academico="Pregrado",
    )

    assert script_pregrado.startswith("#SingleInstance force")
    assert "Send, MEDR{Tab}22180{Tab}{Tab}4.2{Tab}N{Down}{Space}{Tab}" in script_pregrado
    assert "Send, MEDR{Tab}22280{Tab}{Tab}4.2{Tab}N" in script_pregrado
    assert "{Tab}P" not in script_pregrado
    assert not script_pregrado.rstrip().endswith("{Down}{Space}{Tab}")

    script_posgrado = generar_script_ahk_desde_registros(
        registros,
        nivel_academico="Posgrado",
    )

    assert script_posgrado.startswith("#SingleInstance force")
    assert "Send, MEDR{Tab}22180{Tab}{Tab}4.15{Tab}P{Down}{Space}{Tab}" in script_posgrado
    assert "Send, MEDR{Tab}22280{Tab}{Tab}4.20{Tab}P" in script_posgrado
    assert "{Tab}N" not in script_posgrado
    assert not script_posgrado.rstrip().endswith("{Down}{Space}{Tab}")

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

    script_json, data = generar_ahk_desde_respuesta_json(respuesta)

    assert data["estado"] == "ok"
    assert "Send, MEDR{Tab}22180{Tab}{Tab}4.50{Tab}P{Down}{Space}{Tab}" in script_json
    assert "Send, MEDR{Tab}22280{Tab}{Tab}4.20{Tab}P" in script_json

    print("✅ Self-test OK")
    print()
    print("PREGRADO:")
    print(script_pregrado)
    print("POSGRADO:")
    print(script_posgrado)


if __name__ == "__main__":
    _self_test()