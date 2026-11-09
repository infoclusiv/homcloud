"""Prueba terminal del modelo OpenRouter :batch sin archivos reales.

POST /api/v1/batches (modelo BASE), después GET /api/v1/batches/{id}.
Siempre imprime el batch_id tan pronto se acepta para retomar sin duplicados.
El prompt es inventado ("Responde solamente OK.") y se exige aprobación
--permitir-pago para crear un lote facturable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

from diagnostico_openrouter_terminal import _consulta, _resumir_error
from openrouter_cliente import (
    obtener_api_key_openrouter, verificar_api_key_openrouter,
    fuente_api_key_openrouter, modelo_valido, listar_modelos_openrouter,
)

BATCHES_URL = "https://openrouter.ai/api/v1/batches"
MODEL = "deepseek/deepseek-v4.1-flash-1017:batch"
ESTADOS_FINALES = {"completed", "failed", "expired", "cancelled"}
CUSTOM_ID = "homcloud-prueba-tecnica-sin-documentos"
RE_BATCH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,190}$")


def _print(datos: dict) -> None:
    print(json.dumps(datos, ensure_ascii=False, indent=2), flush=True)


def _validar_modelo(modelo: str) -> str:
    if not (modelo_valido(modelo) and modelo.endswith(":batch")):
        raise ValueError("Se requiere el identificador exacto de un modelo terminado en :batch.")
    return modelo[:-6]


def _detalle_error(dato: object, clave: str) -> dict:
    return _resumir_error(dato, clave)


def _mostrar_lote(dato: object, *, batch_id: str, http: int | None, clave: str) -> tuple[str | None, bool]:
    if not isinstance(dato, dict):
        _print({"batch_id": batch_id, "http": http, "error": "Respuesta JSON inesperada."})
        return None, False
    estado = dato.get("status")
    info = {
        "batch_id": batch_id,
        "http": http,
        "estado": estado,
        "modelo": str(dato.get("model") or "")[:190],
    }
    counts = dato.get("request_counts")
    if isinstance(counts, dict):
        info["solicitudes"] = {
            nombre: counts[nombre]
            for nombre in ("total", "completed", "failed")
            if isinstance(counts.get(nombre), int)
        }
    usage = dato.get("usage")
    if isinstance(usage, dict):
        info["consumo"] = {
            k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cost")
            if isinstance(usage.get(k), (float, int)) and not isinstance(usage[k], bool)
        }
    if dato.get("error"):
        info["error_lote"] = _detalle_error(
            {"error": dato["error"]}, clave,
        )
    ok = False
    if estado == "completed" and isinstance(dato.get("results"), list):
        matches = [
            item for item in dato["results"]
            if isinstance(item, dict) and item.get("custom_id") == CUSTOM_ID
        ]
        if matches:
            item = matches[0]
            if item.get("error"):
                info["error_solicitud"] = _detalle_error({"error": item["error"]}, clave)
            else:
                response = item.get("response") or {}
                body = response.get("body") if isinstance(response, dict) else {}
                if not isinstance(body, dict):
                    body = {}
                choices = body.get("choices") or []
                msg = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
                answer = msg.get("content") if isinstance(msg, dict) else None
                info["respuesta_ok"] = bool(isinstance(answer, str) and "OK" in answer.upper())
                info["respuesta_contiene_texto"] = bool(isinstance(answer, str) and answer.strip())
                info["http_solicitud"] = response.get("status_code")
                ok = response.get("status_code") == 200 and info["respuesta_contiene_texto"]
    _print(info)
    return estado if isinstance(estado, str) else None, ok


def ejecutar(*, modelo: str, solo_lectura: bool, permitir_pago: bool,
            esperar: int, consultar_batch: str | None, timeout: int) -> int:
    clave = obtener_api_key_openrouter()
    origen = fuente_api_key_openrouter()
    valid = verificar_api_key_openrouter(timeout=timeout)
    _print({
        "autenticacion": "correcta" if valid.get("ok") else "fallida",
        "http_key": valid.get("http_status"),
        "origen_clave": origen["origen"],
        "envio_inferencia": False if solo_lectura else not bool(consultar_batch),
    })
    if not valid.get("ok"):
        return 2

    if consultar_batch is not None:
        if not RE_BATCH_ID.fullmatch(consultar_batch):
            _print({"error": "ID de lote inválido; no se realizó ninguna petición."})
            return 2
        http, data = _consulta(
            BATCHES_URL + "/" + consultar_batch,
            clave, timeout=timeout,
        )
        if http != 200:
            _print({
                "http_batch": http,
                "batch_id": consultar_batch,
                "error": _detalle_error(data, clave),
            })
            return 1
        estado, ok = _mostrar_lote(data, batch_id=consultar_batch, http=http, clave=clave)
        resultados_pendientes = (
            estado == "completed"
            and (not isinstance(data, dict) or data.get("results") is None)
        )
        if resultados_pendientes:
            _print({"mensaje": "La ejecución terminó; los resultados aún no están disponibles. Consulta el mismo batch_id."})
        return 0 if estado in ESTADOS_FINALES and ok else (
            3 if estado not in ESTADOS_FINALES or resultados_pendientes else 1
        )

    base = _validar_modelo(modelo)
    catalogo = listar_modelos_openrouter(timeout=timeout)
    _print({
        "modelo_elegido": modelo,
        "modelo_normal_para_batch": base,
        "presente_en_catalogo": (
            modelo in catalogo.get("models", []) if catalogo.get("ok") else "catálogo no disponible"
        ),
        "endpoint_correcto": "POST /api/v1/batches",
        "endpoint_incorrecto": "POST /api/v1/chat/completions con :batch",
    })
    if solo_lectura:
        _print({"modo": "solo lectura", "se_creo_lote": False, "coste": "ninguno por inferencia"})
        return 0
    if not permitir_pago:
        _print({
            "se_creo_lote": False,
            "mensaje": "Este modelo es de pago. Para una prueba real añade --permitir-pago.",
        })
        return 2
    payload = {
        "endpoint": "/v1/chat/completions",
        "model": base,  # Nota: OpenRouter exige el slug SIN :batch en el POST.
        "requests": [{
            "custom_id": CUSTOM_ID,
            "body": {
                "messages": [{"role": "user", "content": "Responde solamente OK."}],
                "max_tokens": 256,
            },
        }],
    }
    http, dato = _consulta(BATCHES_URL, clave, payload=payload, timeout=timeout)
    if http not in (200, 201, 202) or not isinstance(dato, dict):
        _print({"http_creacion": http, "lote_creado": False, "error": _detalle_error(dato, clave)})
        return 1
    batch_id = dato.get("id")
    if not isinstance(batch_id, str) or not RE_BATCH_ID.fullmatch(batch_id):
        _print({"http_creacion": http, "aviso": "Lote posiblemente aceptado, pero ID inesperado. No repitas el POST automáticamente."})
        return 1
    _print({
        "http_creacion": http,
        "batch_id": batch_id,
        "estado_inicial": dato.get("status"),
        "importante": "Lote enviado. Guarda batch_id y usa --consultar-batch para continuar sin crear otro.",
    })

    deadline = time.monotonic() + max(0, esperar)
    while time.monotonic() < deadline:
        delay = min(30.0, max(0.0, deadline - time.monotonic()))
        if delay:
            time.sleep(delay)
        status, data = _consulta(BATCHES_URL + "/" + batch_id, clave, timeout=timeout)
        if status != 200:
            _print({"http_consulta": status, "batch_id": batch_id, "error": _detalle_error(data, clave)})
            return 1
        estado, ok = _mostrar_lote(data, batch_id=batch_id, http=status, clave=clave)
        if estado == "completed" and isinstance(data, dict) and data.get("results") is None:
            continue  # OpenRouter puede finalizar antes de publicar resultados.
        if estado in ESTADOS_FINALES:
            return 0 if ok else 1
    _print({
        "estado": "seguimiento_pendiente",
        "batch_id": batch_id,
        "consulta": (
            ".venv/bin/python -m diagnostico_openrouter_batch --consultar-batch "
            + batch_id
        ),
        "nota": "No se creó otro lote; los trabajos batch pueden tardar minutos u horas.",
    })
    return 3


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Probar modelos OpenRouter :batch usando la API asíncrona real"
    )
    parser.add_argument("--modelo", default=MODEL, help="ID terminado en :batch")
    parser.add_argument("--solo-lectura", action="store_true")
    parser.add_argument("--permitir-pago", action="store_true")
    parser.add_argument("--esperar", type=int, default=90,
                        help="Segundos para seguir el lote, máximo 600; al finalizar imprime ID")
    parser.add_argument("--consultar-batch", help="Consultar ID anterior sin crear más trabajo")
    parser.add_argument("--timeout", type=int, default=25, help="Timeout de cada petición HTTP")
    args = parser.parse_args(argv)
    if not 0 <= args.esperar <= 600 or not 5 <= args.timeout <= 90:
        parser.error("--esperar debe ser 0..600; --timeout 5..90.")
    try:
        return ejecutar(
            modelo=args.modelo, solo_lectura=args.solo_lectura,
            permitir_pago=args.permitir_pago, esperar=args.esperar,
            consultar_batch=args.consultar_batch, timeout=args.timeout,
        )
    except ValueError as exc:
        print("ERROR:", str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "\nInterrumpido. Si ya viste batch_id, retoma con --consultar-batch; "
            "no repitas el envío.", file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
