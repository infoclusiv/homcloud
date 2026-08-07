from pathlib import Path


EXTENSIONES_CARGA_STREAMLIT = ("pdf", "xlsx", "xls")
EXTENSIONES_DOCUMENTO_SOPORTADAS = {f".{ext}" for ext in EXTENSIONES_CARGA_STREAMLIT}
EXTENSIONES_EXCEL = {".xlsx", ".xls"}


def extension_documento(archivo) -> str:
    """Devuelve la extensión normalizada de un nombre o Path."""
    return Path(str(archivo or "")).suffix.lower()


def es_documento_soportado(archivo) -> bool:
    return extension_documento(archivo) in EXTENSIONES_DOCUMENTO_SOPORTADAS


def tipo_documento_para_archivo(archivo) -> str:
    extension = extension_documento(archivo)
    if extension == ".pdf":
        return "PDF"
    if extension in EXTENSIONES_EXCEL:
        return "Excel"
    raise ValueError(
        f"Tipo de archivo no soportado: {extension or 'sin extensión'}. "
        "Solo se permiten PDF, XLSX y XLS."
    )


def modo_llmwhisperer_para_archivo(archivo) -> str:
    """Selecciona el modo compatible de LLMWhisperer según el tipo de documento."""
    extension = extension_documento(archivo)
    if extension == ".pdf":
        return "high_quality"
    if extension in EXTENSIONES_EXCEL:
        # LLMWhisperer procesa MS Office Excel mediante form mode.
        return "form"
    raise ValueError(
        f"Tipo de archivo no soportado: {extension or 'sin extensión'}. "
        "Solo se permiten PDF, XLSX y XLS."
    )
