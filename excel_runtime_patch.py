"""Parche de compatibilidad para extender el pipeline actual de PDF a Excel.

La aplicación principal todavía conserva nombres internos históricos como `procesar_pdf`
para minimizar riesgo. Este módulo cambia únicamente los puntos donde el tipo de archivo
sí importa: subida, modo de LLMWhisperer y textos de interfaz.
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


def _reemplazar_una_vez(source: str, old: str, new: str, descripcion: str) -> str:
    cantidad = source.count(old)
    if cantidad != 1:
        raise RuntimeError(
            f"No se pudo aplicar soporte Excel ({descripcion}): "
            f"se esperaban 1 coincidencia y se encontraron {cantidad}."
        )
    return source.replace(old, new, 1)


def aplicar_soporte_excel(source: str) -> str:
    source = _reemplazar_una_vez(
        source,
        _OLD_LLMWHISPERER_BLOCK,
        _NEW_LLMWHISPERER_BLOCK,
        "parser LLMWhisperer",
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
