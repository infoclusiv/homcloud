"""Diagnóstico técnico de OpenRouter, totalmente desde terminal.

Comprueba la API key y el catálogo/los endpoints sin inferencia. Solo realiza
una petición con un prompt sintético si no se incluye --solo-lectura.
Nunca imprime credenciales, headers, prompts ni cuerpos de documentos.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from urllib import error, parse, request

from openrouter_cliente import (
    obtener_api_key_openrouter,
    fuente_api_key_openrouter,
    listar_modelos_openrouter,
    modelo_gratuito,
    modelo_valido,
    verificar_api_key_openrouter,
    URL_CHAT,
)


def _resumir_error(data: object, clave: str) -> dict:
    """Solo errores del prompt inocuo, nunca cuerpo HTTP sin sanitizar."""
    if not isinstance(data, dict):
        return {"mensaje": "Respuesta no JSON; no se mostrará su cuerpo."}
    fallo = data.get("error")
    if not isinstance(fallo, dict):
        return {"mensaje": "No se encontró un objeto error en la respuesta."}
    msg = fallo.get("message", "")
    if not isinstance(msg, str):
        msg = ""
    if clave:
        msg = msg.replace(clave, "[CLAVE OCULTA]")
    msg = re.sub(r"(?i)bearer\s+\S+", "Bearer [OCULTO]", msg)
    msg = re.sub(r"\bsk-or-[\w-]+\b", "[CLAVE OCULTA]", msg)
    msg = re.sub(r"[\w.+-]+@[\w.-]+\.[\w.-]+", "[EMAIL OCULTO]", msg)
    msg = re.sub(r"https?://\S+", "[URL OCULTA]", msg)
    msg = re.sub(r"[\x00-\x1f\x7f]", " ", msg)
    codigo = fallo.get("code")
    return {
        "mensaje": msg[:500],
        "codigo": codigo if isinstance(codigo, int) and not isinstance(codigo, bool) else None,
    }


def _consulta(url: str, clave: str, *, payload: dict | None = None, timeout: int = 20) -> tuple[int | None, object]:
    headers = {
        "Authorization": f"Bearer {clave}",
        "Accept": "application/json",
        "User-Agent": "homcloud-diagnostico/1",
    }
    cuerpo = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    solicitud = request.Request(
        url,
        data=cuerpo,
        headers=headers,
        method="POST" if cuerpo is not None else "GET",
    )
    try:
        with request.urlopen(solicitud, timeout=timeout) as resp:
            datos = resp.read(128_001)
            status = resp.getcode() if hasattr(resp, "getcode") else 200
        if len(datos) > 128_000:
            return status, {"error": {"message": "Respuesta demasiado grande para diagnóstico"}}
        try:
            return status, json.loads(datos)
        except (ValueError, UnicodeError):
            return status, {}
    except error.HTTPError as exc:
        try:
            datos = exc.read(32_001)
            parsed = json.loads(datos) if len(datos) <= 32_000 else {}
        except (OSError, ValueError, UnicodeError):
            parsed = {}
        return exc.code, parsed
    except (error.URLError, OSError, TimeoutError):
        return None, {"error": {"message": "No se pudo conectar o la solicitud agotó el tiempo"}}


def _orientacion(status: int | None, existe: bool | None, endpoints: int | None) -> str:
    if status == 404:
        if existe is False:
            return "El ID no aparece en el catálogo actual: revisa el modelo exacto."
        if endpoints == 0:
            return "El modelo figura en el catálogo pero no expone endpoints: puede estar sin proveedor."
        return (
            "OpenRouter no encontró un endpoint compatible para esa petición. "
            "Revisa disponibilidad, privacidad/ruteo de cuenta y el mensaje del proveedor."
        )
    if status == 401:
        return "La petición de inferencia devolvió 401 pese a la comprobación de clave: revisar políticas de acceso."
    if status == 402:
        return "OpenRouter rechazó la petición por saldo o límites de gasto."
    if status == 429:
        return "Límite de solicitudes del proveedor/modelo o de la cuenta."
    if status is None:
        return "Error de conexión: revisar DNS, TLS y red de Cloud Shell."
    if status and status >= 500:
        return "Error del proveedor o del servicio de inferencia."
    return ""


def diagnosticar(modelo: str, *, solo_lectura: bool, permitir_pago: bool, timeout: int) -> tuple[dict, int]:
    resultado = {
        "modelo": modelo,
        "consulta_key": None,
        "catalogo": None,
        "modelo_en_catalogo": None,
        "endpoints_http": None,
        "cantidad_endpoints": None,
        "inferencia_http": "no ejecutada",
        "respuesta": None,
        "error_openrouter": None,
        "orientacion": None,
    }
    if not modelo_valido(modelo):
        resultado["orientacion"] = "ID de modelo inválido. Usa autor/slug exacto."
        return resultado, 2
    fuente = fuente_api_key_openrouter()
    resultado["origen_credencial"] = fuente["origen"]
    resultado["existe_archivo_privado"] = fuente["archivo_privado"]
    resultado["existe_variable_entorno"] = fuente["entorno_env"]
    clave = obtener_api_key_openrouter()
    validacion = verificar_api_key_openrouter(timeout=timeout)
    resultado["consulta_key"] = {
        "http": validacion.get("http_status"),
        "reconocida": bool(validacion.get("ok")),
        "mensaje": validacion.get("mensaje"),
    }
    if not validacion.get("ok"):
        resultado["orientacion"] = "La API key no superó GET /key; no se envió una inferencia."
        return resultado, 2
    catalogo = listar_modelos_openrouter(timeout=timeout)
    resultado["catalogo"] = "accesible" if catalogo["ok"] else catalogo.get("error")
    existe = (modelo in catalogo.get("models", [])) if catalogo["ok"] else None
    resultado["modelo_en_catalogo"] = existe

    if modelo != "openrouter/free" and "/" in modelo:
        author, slug = modelo.split("/", 1)
        ruta = (
            "https://openrouter.ai/api/v1/models/"
            + parse.quote(author, safe="")
            + "/" + parse.quote(slug, safe=":")
            + "/endpoints"
        )
        status, data = _consulta(ruta, clave, timeout=timeout)
        resultado["endpoints_http"] = status
        endpoints = data.get("data", {}).get("endpoints") if isinstance(data, dict) and isinstance(data.get("data"), dict) else None
        if isinstance(endpoints, list):
            resultado["cantidad_endpoints"] = len(endpoints)

    if solo_lectura:
        resultado["orientacion"] = "Solo lectura. No se generaron tokens ni cargos por inferencia."
        return resultado, 0
    if not modelo_gratuito(modelo) and not permitir_pago:
        resultado["orientacion"] = (
            "Es un modelo de pago. Para autorizar una petición sintética "
            "añade explícitamente --permitir-pago."
        )
        return resultado, 2

    # Una única solicitud con contenido totalmente ficticio. No usar TXT.
    payload = {
        "model": modelo,
        "messages": [{"role": "user", "content": "Responde solo OK."}],
        "max_tokens": 64,
        "stream": False,
    }
    status, data = _consulta(URL_CHAT, clave, payload=payload, timeout=timeout)
    resultado["inferencia_http"] = status
    if status == 200 and isinstance(data, dict):
        opciones = data.get("choices") or []
        mensaje = opciones[0].get("message") if opciones and isinstance(opciones[0], dict) else None
        texto = mensaje.get("content") if isinstance(mensaje, dict) else None
        resultado["respuesta"] = (
            str(texto)[:120] if texto is not None else "(sin contenido de texto)"
        )
        resultado["modelo_respondio"] = str(data.get("model") or "")[:180]
        usage = data.get("usage")
        if isinstance(usage, dict):
            resultado["tokens"] = {
                k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                if isinstance(usage.get(k), int)
            }
        resultado["orientacion"] = "La API de inferencia respondió HTTP 200."
        return resultado, 0
    resultado["error_openrouter"] = _resumir_error(data, clave)
    resultado["orientacion"] = _orientacion(
        status, existe, resultado["cantidad_endpoints"]
    )
    return resultado, 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnóstico OpenRouter por terminal, sin documentos ni claves visibles"
    )
    parser.add_argument("--modelo", required=True, help="ID exacto del selector web, como openrouter/free")
    parser.add_argument("--solo-lectura", action="store_true", help="No realizar inferencia")
    parser.add_argument("--permitir-pago", action="store_true", help="Autorizar una petición real facturable")
    parser.add_argument("--timeout", type=int, default=25)
    args = parser.parse_args(argv)
    if not 5 <= args.timeout <= 90:
        parser.error("--timeout debe estar entre 5 y 90 segundos.")
    resultado, salida = diagnosticar(
        args.modelo.strip(), solo_lectura=args.solo_lectura,
        permitir_pago=args.permitir_pago, timeout=args.timeout,
    )
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return salida


if __name__ == "__main__":
    sys.exit(main())
