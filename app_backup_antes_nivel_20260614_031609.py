import streamlit as st
from pathlib import Path
import os
import json
import re
import csv
import traceback
import subprocess
import shutil
from datetime import datetime
from dotenv import load_dotenv

from unstract.llmwhisperer import LLMWhispererClientV2
from unstract.llmwhisperer.client_v2 import LLMWhispererClientException


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
RUNS_DIR = OUTPUTS_DIR / "runs"

UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(dotenv_path=ENV_PATH)


PROMPT_DEFAULT = """Analiza el archivo adjunto. El documento es un acta de homologación.

Debes responder basándote ÚNICAMENTE en el contenido del archivo.

Extrae los siguientes campos y responde exactamente con este formato:

NOMBRE_ESTUDIANTE:
PROGRAMA_ASPIRA:
PLAN_ESTUDIO:
NOMBRE_PROGRAMA_ORIGEN:
CREDITOS_HOMOLOGADOS:

Reglas:
- No inventes información.
- Si un dato no aparece claramente, escribe: No extraído.
- CREDITOS_HOMOLOGADOS debe ser solo un número entero.
- No agregues explicación adicional.
"""


def sanitizar_nombre_archivo(nombre: str) -> str:
    nombre = re.sub(r'[<>:"/\\|?*]', "", nombre)
    nombre = nombre.replace("\n", " ").replace("\r", " ").strip()
    nombre = re.sub(r"\s+", " ", nombre)
    return nombre or "documento.pdf"


def limpiar_texto_para_llm(texto: str) -> str:
    if not texto:
        return ""

    texto = texto.replace("<<<\x0c", "\n\n--- NUEVA PÁGINA ---\n\n")
    texto = texto.replace("\f", "\n\n--- NUEVA PÁGINA ---\n\n")

    while "\n\n\n" in texto:
        texto = texto.replace("\n\n\n", "\n\n")

    return texto.strip()


def quitar_ansi(texto: str) -> str:
    if not texto:
        return ""
    return re.sub(r"\x1b\[[0-9;]*m", "", texto)


def obtener_api_keys_llmwhisperer():
    keys = []

    for i in range(1, 4):
        key = os.getenv(f"LLMWHISPERER_API_KEY_{i}")
        if key and key.strip():
            keys.append((i, key.strip()))

    return keys


def parsear_pdf_con_llmwhisperer(pdf_path: Path):
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


def guardar_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def ejecutar_opencode(prompt: str, txt_path: Path):
    opencode_path = shutil.which("opencode")

    if not opencode_path:
        return {
            "ok": False,
            "error": "No se encontró el comando opencode en el PATH.",
        }

    if not txt_path.exists():
        return {
            "ok": False,
            "error": f"No existe el archivo TXT: {txt_path}",
        }

    try:
        comando = [
            opencode_path,
            "run",
            prompt,
            "--file",
            str(txt_path),
        ]

        proceso = subprocess.run(
            comando,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=900,
        )

        stdout = quitar_ansi(proceso.stdout or "")
        stderr = quitar_ansi(proceso.stderr or "")

        return {
            "ok": proceso.returncode == 0,
            "returncode": proceso.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "command": comando,
        }

    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "error": "OpenCode tardó demasiado y se canceló por timeout.",
            "stdout": quitar_ansi(e.stdout or ""),
            "stderr": quitar_ansi(e.stderr or ""),
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def extraer_campo(texto: str, etiqueta: str, default: str = "No extraído") -> str:
    if not texto:
        return default

    patron = rf"{re.escape(etiqueta)}\s*:\s*(.*)"
    match = re.search(patron, texto, re.IGNORECASE)

    if not match:
        return default

    valor = match.group(1).strip().strip("*").strip()
    return valor or default


def extraer_datos_respuesta_opencode(respuesta: str):
    creditos = extraer_campo(respuesta, "CREDITOS_HOMOLOGADOS", "0")
    creditos_num = re.search(r"\d+", creditos)
    creditos = creditos_num.group(0) if creditos_num else "0"

    return {
        "Nombre": extraer_campo(respuesta, "NOMBRE_ESTUDIANTE"),
        "Programa al que aspira": extraer_campo(respuesta, "PROGRAMA_ASPIRA"),
        "Plan": extraer_campo(respuesta, "PLAN_ESTUDIO"),
        "Programa origen": extraer_campo(respuesta, "NOMBRE_PROGRAMA_ORIGEN"),
        "Créditos homologados": creditos,
    }


def guardar_csv_resumen(path: Path, filas: list):
    if not filas:
        return

    fieldnames = list(filas[0].keys())

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filas)


def procesar_pdf(uploaded_file, prompt: str, run_uploads_dir: Path, run_outputs_dir: Path):
    nombre_seguro = sanitizar_nombre_archivo(uploaded_file.name)
    pdf_path = run_uploads_dir / nombre_seguro

    with open(pdf_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    stem = Path(nombre_seguro).stem

    txt_path = run_outputs_dir / f"{stem}_llmwhisperer.txt"
    llmwhisperer_json_path = run_outputs_dir / f"{stem}_llmwhisperer_raw.json"
    opencode_txt_path = run_outputs_dir / f"{stem}_opencode.txt"
    opencode_json_path = run_outputs_dir / f"{stem}_opencode.json"

    fila = {
        "Archivo": nombre_seguro,
        "Estado": "Iniciado",
        "Nombre": "",
        "Programa al que aspira": "",
        "Plan": "",
        "Programa origen": "",
        "Créditos homologados": "",
        "TXT LLMWhisperer": "",
        "Respuesta OpenCode": "",
        "Error": "",
    }

    resultado_parseo = parsear_pdf_con_llmwhisperer(pdf_path)
    guardar_json(llmwhisperer_json_path, resultado_parseo)

    if not resultado_parseo.get("ok"):
        fila["Estado"] = "Error LLMWhisperer"
        fila["Error"] = json.dumps(resultado_parseo, ensure_ascii=False)
        return fila

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(resultado_parseo["text"])

    fila["TXT LLMWhisperer"] = str(txt_path)

    resultado_opencode = ejecutar_opencode(prompt=prompt, txt_path=txt_path)
    guardar_json(opencode_json_path, resultado_opencode)

    respuesta = resultado_opencode.get("stdout", "")

    with open(opencode_txt_path, "w", encoding="utf-8") as f:
        f.write(respuesta)

    fila["Respuesta OpenCode"] = str(opencode_txt_path)

    if not resultado_opencode.get("ok"):
        fila["Estado"] = "Error OpenCode"
        fila["Error"] = resultado_opencode.get("stderr") or resultado_opencode.get("error", "")
        return fila

    datos = extraer_datos_respuesta_opencode(respuesta)
    fila.update(datos)
    fila["Estado"] = "Completado"

    return fila


st.set_page_config(
    page_title="PDF Batch Parser",
    page_icon="📄",
    layout="wide",
)

st.title("📄 Procesador por lote: LLMWhisperer + OpenCode CLI")

st.write(
    "Selecciona varios PDFs, edita el prompt una sola vez y ejecuta todo el flujo con un clic."
)

api_keys = obtener_api_keys_llmwhisperer()
opencode_path = shutil.which("opencode")

col1, col2 = st.columns(2)

with col1:
    if api_keys:
        st.success(f"✅ {len(api_keys)} API key(s) de LLMWhisperer encontradas")
    else:
        st.error("❌ No se encontraron API keys de LLMWhisperer en .env")

with col2:
    if opencode_path:
        st.success(f"✅ OpenCode encontrado: {opencode_path}")
    else:
        st.error("❌ No se encontró OpenCode en el PATH")

st.divider()

st.header("1. Editar prompt para OpenCode")

prompt = st.text_area(
    "Este prompt se enviará a OpenCode para analizar cada TXT generado por LLMWhisperer.",
    value=PROMPT_DEFAULT,
    height=320,
)

st.header("2. Seleccionar PDFs")

uploaded_files = st.file_uploader(
    "Selecciona uno o varios archivos PDF",
    type=["pdf"],
    accept_multiple_files=True,
)

if uploaded_files:
    st.info(f"📚 PDFs seleccionados: {len(uploaded_files)}")

    with st.expander("Ver archivos seleccionados", expanded=False):
        for file in uploaded_files:
            st.write(f"- {file.name} ({len(file.getvalue())} bytes)")

st.header("3. Ejecutar procesamiento completo")

disabled = not uploaded_files or not prompt.strip() or not api_keys or not opencode_path

if st.button("🚀 Procesar PDFs con LLMWhisperer + OpenCode", disabled=disabled):
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_uploads_dir = UPLOADS_DIR / run_id
    run_outputs_dir = RUNS_DIR / run_id

    run_uploads_dir.mkdir(parents=True, exist_ok=True)
    run_outputs_dir.mkdir(parents=True, exist_ok=True)

    prompt_path = run_outputs_dir / "prompt_usado.txt"
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    st.info(f"📁 Carpeta de salida del lote: `{run_outputs_dir}`")

    progress = st.progress(0)
    status_placeholder = st.empty()
    table_placeholder = st.empty()

    filas = []
    total = len(uploaded_files)

    for index, uploaded_file in enumerate(uploaded_files, start=1):
        status_placeholder.write(
            f"Procesando {index}/{total}: **{uploaded_file.name}**"
        )

        try:
            fila = procesar_pdf(
                uploaded_file=uploaded_file,
                prompt=prompt,
                run_uploads_dir=run_uploads_dir,
                run_outputs_dir=run_outputs_dir,
            )
        except Exception as e:
            fila = {
                "Archivo": uploaded_file.name,
                "Estado": "Error inesperado",
                "Nombre": "",
                "Programa al que aspira": "",
                "Plan": "",
                "Programa origen": "",
                "Créditos homologados": "",
                "TXT LLMWhisperer": "",
                "Respuesta OpenCode": "",
                "Error": str(e) + "\\n" + traceback.format_exc(),
            }

        filas.append(fila)
        progress.progress(index / total)
        table_placeholder.dataframe(filas, use_container_width=True)

    resumen_csv_path = run_outputs_dir / "resumen_resultados.csv"
    guardar_csv_resumen(resumen_csv_path, filas)

    status_placeholder.success("✅ Procesamiento por lote finalizado")

    completados = sum(1 for f in filas if f.get("Estado") == "Completado")
    errores = total - completados

    col_ok, col_error, col_total = st.columns(3)
    col_ok.metric("Completados", completados)
    col_error.metric("Errores", errores)
    col_total.metric("Total", total)

    st.subheader("Resumen final")
    st.dataframe(filas, use_container_width=True)

    with open(resumen_csv_path, "rb") as f:
        st.download_button(
            label="⬇️ Descargar CSV de resultados",
            data=f,
            file_name="resumen_resultados.csv",
            mime="text/csv",
        )

    st.write(f"**Prompt usado:** `{prompt_path}`")
    st.write(f"**CSV generado:** `{resumen_csv_path}`")
    st.write(f"**Carpeta completa del lote:** `{run_outputs_dir}`")

st.divider()
st.caption("Recomendación: para la primera prueba usa 2 o 3 PDFs antes de correr 30 o 40.")
