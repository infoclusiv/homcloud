"""Selección y validación de proveedor para reintentos de lotes.

No ejecuta APIs ni modifica preferencias globales o locales. Las reglas pueden
probarse sin Streamlit y se usan únicamente al volver a procesar filas fallidas.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from preferencias_motor import modelo_id_valido


PROVEEDORES_REINTENTO = (
    "Seleccionar un proveedor...",
    "OpenCode",
    "OpenRouter",
    "ChatGPT OAuth",
)


def proveedor_desde_modelo(modelo: str | None) -> str:
    """Traduce el identificador persistido del modelo a su proveedor."""
    valor = str(modelo or "").strip().lower()
    if valor.startswith("openrouter::"):
        return "OpenRouter"
    if valor.startswith("chatgpt::"):
        return "ChatGPT OAuth"
    return "OpenCode"


def causas_reintentables(filas: Iterable[dict]) -> dict[str, int]:
    """Muestra motivos resumidos sin publicar textos de errores sensibles."""
    conteo: Counter[str] = Counter()
    for fila in filas:
        estado = str(fila.get("Estado") or "").casefold()
        error = str(fila.get("Error") or "").casefold()
        texto = estado + " " + error
        if any(token in texto for token in ("429", "rate limit", "rate_limit", "cuota", "cupo", "límite", "limite")):
            motivo = "Límite de uso o solicitudes"
        elif "llmwhisperer" in texto or "extracci" in estado:
            motivo = "Extracción LLMWhisperer"
        elif "timeout" in texto or "tiempo máximo" in texto or "tiempo maximo" in texto:
            motivo = "Tiempo de espera agotado"
        elif "json" in estado or "formato" in estado:
            motivo = "Respuesta IA no válida"
        elif any(token in estado for token in ("opencode", "openrouter", "oauth", "proveedor")):
            motivo = "Fallo del proveedor de IA"
        else:
            motivo = "Otros errores técnicos"
        conteo[motivo] += 1
    return dict(conteo)


def requisitos_reintento(
    proveedor: str,
    modelo: str,
    *,
    hay_llmwhisperer: bool,
    prompts_validos: bool,
    ajustes_validos: bool,
    opencode_instalado: bool,
    openrouter_con_clave: bool,
    openrouter_modelo_valido: bool,
    openrouter_es_pago: bool,
    pago_confirmado: bool,
    oauth_actas_autorizadas: bool,
    oauth_sesion_valida: bool,
    oauth_modelo_disponible: bool,
) -> list[str]:
    """Valida selección y permisos antes de gastar llamadas de extracción."""
    errores: list[str] = []
    if proveedor not in PROVEEDORES_REINTENTO[1:]:
        return ["selecciona un proveedor para el reintento"]
    if not hay_llmwhisperer:
        errores.append("configura las API keys de LLMWhisperer")
    if not prompts_validos:
        errores.append("configura los prompts de Pregrado y Posgrado")
    if not ajustes_validos:
        errores.append("recarga o corrige los ajustes compartidos antes de reintentar")

    if proveedor == "OpenCode":
        if not opencode_instalado:
            errores.append("instala o habilita OpenCode en el PATH")
        if not modelo_id_valido(modelo) or modelo.startswith(("openrouter::", "chatgpt::")):
            errores.append("introduce un modelo OpenCode válido")
    elif proveedor == "OpenRouter":
        if not openrouter_con_clave:
            errores.append("guarda una API key de OpenRouter en este Cloud Shell")
        if not modelo.startswith("openrouter::") or not openrouter_modelo_valido:
            errores.append("selecciona un modelo válido de OpenRouter")
        if modelo.endswith(":batch"):
            errores.append("los modelos OpenRouter :batch no se ejecutan en este flujo")
        if openrouter_es_pago and not pago_confirmado:
            errores.append("confirma explícitamente el uso del modelo de pago")
    elif proveedor == "ChatGPT OAuth":
        if not oauth_actas_autorizadas:
            errores.append("autoriza el procesamiento de actas con ChatGPT OAuth")
        if not oauth_sesion_valida:
            errores.append("inicia sesión OAuth en este Cloud Shell")
        if not modelo.startswith("chatgpt::") or not modelo.split("::", 1)[-1]:
            errores.append("selecciona un modelo de ChatGPT OAuth")
        elif not oauth_modelo_disponible:
            errores.append("consulta y selecciona un modelo disponible en tu sesión OAuth")
    return errores
