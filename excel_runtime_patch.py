"""Parche de compatibilidad para extender el pipeline actual de PDF a Excel.

La aplicación principal todavía conserva nombres internos históricos como `procesar_pdf`
para minimizar riesgo. Este módulo cambia únicamente los puntos donde el tipo de archivo
sí importa: subida, modo de LLMWhisperer y textos de interfaz. También aplica ajustes
puntuales de UI sobre `app_core.py` sin duplicar su lógica principal.
"""


_OLD_LLMWHISPERER_BLOCK = '''def parsear_pdf_con_llmwhisperer(pdf_path: Path):
    api_keys = obtener_api_keys_llmwhisperer()

    if not api_keys:
        return {
            "ok": False,
            "error": "No se encontró ninguna API key de LLMWhisperer en el archivo .env.",
        }

    last_error = None

    for key_number, api_key in api_keys:
        try:
            client = LLMWhispererClientV2(api_key=api_key)

            result = client.whisper(
                file_path=str(pdf_path),
                wait_for_completion=True,
                wait_timeout=360,
                mode="high_quality",
                output_mode="layout_preserving",
                lang="spa",
            )

            extraction = result.get("extraction", {})
            result_text = extraction.get("result_text")

            if not result_text:
                raise RuntimeError(
                    "LLMWhisperer respondió, pero no devolvió extraction.result_text."
                )

            texto_limpio = limpiar_texto_para_llm(result_text)

            return {
                "ok": True,
                "api_key_used": key_number,
                "pdf_path": str(pdf_path),
                "raw_result": result,
                "text": texto_limpio,
            }

        except LLMWhispererClientException as e:
            last_error = {
                "api_key": key_number,
                "status_code": getattr(e, "status_code", None),
                "error": str(e),
            }
            continue

        except Exception as e:
            last_error = {
                "api_key": key_number,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
            continue

    return {
        "ok": False,
        "error": "No se pudo procesar el PDF con ninguna API key disponible.",
        "last_error": last_error,
    }
'''


_NEW_LLMWHISPERER_BLOCK = '''def parsear_pdf_con_llmwhisperer(pdf_path: Path):
    # El nombre histórico se conserva por compatibilidad con el resto del pipeline,
    # pero la función procesa tanto PDF como Excel.
    from documentos import (
        modo_llmwhisperer_para_archivo,
        tipo_documento_para_archivo,
    )

    try:
        modo_llmwhisperer = modo_llmwhisperer_para_archivo(pdf_path)
        tipo_documento = tipo_documento_para_archivo(pdf_path)
    except ValueError as e:
        return {
            "ok": False,
            "error": str(e),
        }

    api_keys = obtener_api_keys_llmwhisperer()

    if not api_keys:
        return {
            "ok": False,
            "error": "No se encontró ninguna API key de LLMWhisperer en el archivo .env.",
        }

    last_error = None

    for key_number, api_key in api_keys:
        try:
            client = LLMWhispererClientV2(api_key=api_key)

            result = client.whisper(
                file_path=str(pdf_path),
                wait_for_completion=True,
                wait_timeout=360,
                mode=modo_llmwhisperer,
                output_mode="layout_preserving",
                lang="spa",
            )

            extraction = result.get("extraction", {})
            result_text = extraction.get("result_text")

            if not result_text:
                raise RuntimeError(
                    "LLMWhisperer respondió, pero no devolvió extraction.result_text."
                )

            texto_limpio = limpiar_texto_para_llm(result_text)

            return {
                "ok": True,
                "api_key_used": key_number,
                "pdf_path": str(pdf_path),
                "document_path": str(pdf_path),
                "document_type": tipo_documento,
                "llmwhisperer_mode": modo_llmwhisperer,
                "raw_result": result,
                "text": texto_limpio,
            }

        except LLMWhispererClientException as e:
            last_error = {
                "api_key": key_number,
                "status_code": getattr(e, "status_code", None),
                "error": str(e),
            }
            continue

        except Exception as e:
            last_error = {
                "api_key": key_number,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
            continue

    return {
        "ok": False,
        "error": (
            f"No se pudo procesar el archivo {tipo_documento} con ninguna "
            "API key disponible."
        ),
        "last_error": last_error,
    }
'''


_OLD_HEADER_STYLE_BLOCK = '''    .app-shell {
        background: linear-gradient(135deg, #0f172a 0%, #162b63 55%, #1d4ed8 100%);
        border-radius: 22px;
        padding: 1.2rem 1.35rem;
        color: white;
        margin-bottom: 0.95rem;
        box-shadow: 0 18px 40px rgba(15, 23, 42, 0.18);
    }
    .app-shell h1 {
        margin: 0;
        font-size: 2.0rem;
        line-height: 1.1;
        color: white;
    }
    .app-shell p {
        margin: 0.28rem 0 0 0;
        color: rgba(255,255,255,0.86);
        font-size: 1rem;
    }
    .header-grid {
        display:flex;
        align-items:flex-start;
        justify-content:space-between;
        gap: 1rem;
        flex-wrap: wrap;
    }
    .chip-row {
        display:flex;
        gap: 0.7rem;
        flex-wrap: wrap;
        align-items: center;
        justify-content: flex-end;
    }
    .status-chip {
        min-width: 175px;
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 16px;
        padding: 0.7rem 0.9rem;
        backdrop-filter: blur(8px);
    }
    .status-chip .label {
        display:block;
        font-size: 0.78rem;
        color: rgba(255,255,255,0.82);
        margin-bottom: 0.15rem;
    }
    .status-chip .value {
        display:block;
        font-size: 0.98rem;
        font-weight: 700;
        color: #bbf7d0;
    }
'''


_NEW_HEADER_STYLE_BLOCK = '''    .app-shell {
        background: linear-gradient(135deg, #0f172a 0%, #162b63 55%, #1d4ed8 100%);
        border-radius: 18px;
        padding: 0.72rem 1rem;
        color: white;
        margin-bottom: 0.6rem;
        box-shadow: 0 12px 28px rgba(15, 23, 42, 0.16);
    }
    .app-shell h1 {
        margin: 0;
        font-size: 1.65rem;
        line-height: 1.05;
        color: white;
    }
    .app-shell p {
        margin: 0.12rem 0 0 0;
        color: rgba(255,255,255,0.86);
        font-size: 0.86rem;
        line-height: 1.25;
    }
    .header-grid {
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap: 0.75rem;
        flex-wrap: wrap;
    }
    .chip-row {
        display:flex;
        gap: 0.45rem;
        flex-wrap: wrap;
        align-items: center;
        justify-content: flex-end;
    }
    .status-chip {
        min-width: 150px;
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 12px;
        padding: 0.42rem 0.65rem;
        backdrop-filter: blur(6px);
    }
    .status-chip .label {
        display:block;
        font-size: 0.68rem;
        line-height: 1.1;
        color: rgba(255,255,255,0.82);
        margin-bottom: 0.08rem;
    }
    .status-chip .value {
        display:block;
        font-size: 0.88rem;
        line-height: 1.15;
        font-weight: 700;
        color: #bbf7d0;
    }
'''


_OLD_STATUS_CHIP_RENDERER = '''def construir_estado_chip(label: str, value: str) -> str:
    return f"""
    <div class=\"status-chip\">
        <span class=\"label\">{label}</span>
        <span class=\"value\">{value}</span>
    </div>
    """
'''


_NEW_STATUS_CHIP_RENDERER = '''def construir_estado_chip(label: str, value: str) -> str:
    # HTML en una sola línea: evita que Markdown interprete cierres </div>
    # con sangría como bloques de código visibles.
    return (
        f'<div class="status-chip"><span class="label">{label}</span>'
        f'<span class="value">{value}</span></div>'
    )
'''


_OLD_HEADER_MARKUP = '''st.markdown(
    f"""
    <div class=\"app-shell\">
      <div class=\"header-grid\">
        <div>
          <h1>Procesador por lote</h1>
          <p>LLMWhisperer + OpenCode CLI · interfaz compacta para configurar, cargar y procesar sin casi hacer scroll.</p>
        </div>
        <div class=\"chip-row\">
          {construir_estado_chip("API keys LLMWhisperer", api_value)}
          {construir_estado_chip("OpenCode", opencode_value)}
          {construir_estado_chip("Prompts", "Pregrado y Posgrado")}
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)
'''


_NEW_HEADER_MARKUP = '''st.markdown(
    (
        '<div class="app-shell"><div class="header-grid"><div>'
        '<h1>Procesador por lote</h1>'
        '<p>LLMWhisperer + OpenCode CLI · interfaz compacta para configurar, cargar y procesar sin casi hacer scroll.</p>'
        '</div><div class="chip-row">'
        f'{construir_estado_chip("API keys LLMWhisperer", api_value)}'
        f'{construir_estado_chip("OpenCode", opencode_value)}'
        f'{construir_estado_chip("Prompts", "Pregrado y Posgrado")}'
        '</div></div></div>'
    ),
    unsafe_allow_html=True,
)
'''


def _reemplazar_una_vez(source: str, old: str, new: str, descripcion: str) -> str:
    cantidad = source.count(old)
    if cantidad != 1:
        raise RuntimeError(
            f"No se pudo aplicar soporte Excel ({descripcion}): "
            f"se esperaban 1 coincidencia y se encontraron {cantidad}."
        )
    return source.replace(old, new, 1)


def _reemplazar_si_existe_una_vez(
    source: str,
    old: str,
    new: str,
    descripcion: str,
) -> str:
    """Aplica un ajuste opcional cuando la fuente completa contiene ese bloque."""
    cantidad = source.count(old)
    if cantidad > 1:
        raise RuntimeError(
            f"No se pudo aplicar el ajuste de UI ({descripcion}): "
            f"se esperaba como máximo 1 coincidencia y se encontraron {cantidad}."
        )
    if cantidad == 0:
        return source
    return source.replace(old, new, 1)


def aplicar_soporte_excel(source: str) -> str:
    source = _reemplazar_una_vez(
        source,
        _OLD_LLMWHISPERER_BLOCK,
        _NEW_LLMWHISPERER_BLOCK,
        "parser LLMWhisperer",
    )

    # En la aplicación real estos tres bloques existen en app_core.py. Son opcionales
    # para que los tests unitarios que usan una fuente mínima sigan siendo válidos.
    source = _reemplazar_si_existe_una_vez(
        source,
        _OLD_HEADER_STYLE_BLOCK,
        _NEW_HEADER_STYLE_BLOCK,
        "cabecera compacta",
    )
    source = _reemplazar_si_existe_una_vez(
        source,
        _OLD_STATUS_CHIP_RENDERER,
        _NEW_STATUS_CHIP_RENDERER,
        "chips sin HTML indentado",
    )
    source = _reemplazar_si_existe_una_vez(
        source,
        _OLD_HEADER_MARKUP,
        _NEW_HEADER_MARKUP,
        "HTML de cabecera en una sola línea",
    )

    source = _reemplazar_una_vez(
        source,
        '            type=["pdf"],',
        '            type=["pdf", "xlsx", "xls"],',
        "extensiones del uploader",
    )

    reemplazos = {
        'page_title="PDF Batch Parser"': 'page_title="Document Batch Parser"',
        '"PDF activo (min)"': '"Archivo activo (min)"',
        '"📂 Carga de PDFs"': '"📂 Carga de documentos"',
        '"Selecciona uno o varios archivos PDF"': '"Selecciona uno o varios archivos PDF o Excel"',
        '"Arrastra y suelta tus PDFs o selecciónalos manualmente."': '"Arrastra y suelta tus PDF o Excel, o selecciónalos manualmente."',
        '"Limpia los PDFs cargados actualmente para seleccionar una nueva tanda."': '"Limpia los archivos cargados actualmente para seleccionar una nueva tanda."',
        'f"📚 {len(uploaded_files)} PDF(s) listos para procesar"': 'f"📚 {len(uploaded_files)} archivo(s) listos para procesar"',
        '"Todavía no hay PDFs cargados."': '"Todavía no hay archivos cargados."',
        '"Aquí aparecerán los PDFs cargados para revisión rápida."': '"Aquí aparecerán los PDF y Excel cargados para revisión rápida."',
        'requisitos_faltantes.append("cargar al menos un PDF")': 'requisitos_faltantes.append("cargar al menos un archivo PDF o Excel")',
        'f"{resumen[\'procesados\']} de {resumen[\'total\']} PDFs procesados"': 'f"{resumen[\'procesados\']} de {resumen[\'total\']} archivos procesados"',
        '"El archivo adjunto es texto extraído de un PDF por LLMWhisperer."': '"El archivo adjunto es texto extraído de un documento PDF o Excel por LLMWhisperer."',
        '"Enviando PDF a LLMWhisperer y esperando la extracción de texto."': '"Enviando archivo a LLMWhisperer y esperando la extracción de texto."',
        '"LLMWhisperer no pudo extraer el texto del PDF."': '"LLMWhisperer no pudo extraer el texto del archivo."',
        '"PDF procesado correctamente. AHK generado por Python."': '"Archivo procesado correctamente. AHK generado por Python."',
        '"La concurrencia y la relación programa–plan quedan accesibles arriba, antes de cargar los PDFs."': '"La concurrencia y la relación programa–plan quedan accesibles arriba, antes de cargar los PDF o Excel."',
        '"Recomendado: entre 2 y 6. El valor se limita automáticamente al número de PDFs cargados."': '"Recomendado: entre 2 y 6. El valor se limita automáticamente al número de archivos cargados."',
        '"Si un PDF se bloquea, quedará como error reintentable sin detener el resumen final."': '"Si un archivo se bloquea, quedará como error reintentable sin detener el resumen final."',
        '· PDF activo:': '· Archivo activo:',
        'f"🔁 Reintentar {len(filas_error_panel)} PDF(s) con error"': 'f"🔁 Reintentar {len(filas_error_panel)} archivo(s) con error"',
        'f"🔁 Reintentar ahora {len(filas_error_destacadas)} PDF(s) con error"': 'f"🔁 Reintentar ahora {len(filas_error_destacadas)} archivo(s) con error"',
        '"El reintento solo procesará los PDFs con error. Los resultados correctos anteriores se conservarán."': '"El reintento solo procesará los archivos con error. Los resultados correctos anteriores se conservarán."',
        '"Después del reintento, la tabla final quedará combinada: PDFs correctos anteriores + PDFs reintentados actualizados."': '"Después del reintento, la tabla final quedará combinada: archivos correctos anteriores + archivos reintentados actualizados."',
        '"No se pudieron encontrar estos PDFs originales para reintentar: "': '"No se pudieron encontrar estos archivos originales para reintentar: "',
        '"No hay PDFs disponibles para reintentar."': '"No hay archivos disponibles para reintentar."',
        '"Consejo: para una primera prueba, usa 2 o 3 PDFs en paralelo. Si todo funciona bien, luego aumenta gradualmente a 4 o más según la capacidad de tu equipo y la estabilidad de OpenCode."': '"Consejo: para una primera prueba, usa 2 o 3 archivos en paralelo. Si todo funciona bien, luego aumenta gradualmente a 4 o más según la capacidad de tu equipo y la estabilidad de OpenCode."',
    }

    for old, new in reemplazos.items():
        source = source.replace(old, new)

    return source
