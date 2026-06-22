import streamlit as st
from pathlib import Path
import os
import json
import re
import csv
import traceback
import subprocess
import shutil
import zipfile
import unicodedata
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from queue import Queue, Empty
from datetime import datetime
from dotenv import load_dotenv

from ahk_builder import (
    AhkBuilderError,
    extraer_json_desde_respuesta,
    validar_payload_opencode,
    generar_script_ahk_desde_registros,
)

from unstract.llmwhisperer import LLMWhispererClientV2
from unstract.llmwhisperer.client_v2 import LLMWhispererClientException


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
RUNS_DIR = OUTPUTS_DIR / "runs"
PROMPTS_DIR = BASE_DIR / "prompts"
PROMPT_PREGRADO_PATH = PROMPTS_DIR / "pregrado.txt"
PROMPT_POSGRADO_PATH = PROMPTS_DIR / "posgrado.txt"
SETTINGS_DIR = BASE_DIR / "settings"
MODELO_OPENCODE_PERSISTENTE_PATH = SETTINGS_DIR / "modelo_opencode.txt"

UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)
PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(dotenv_path=ENV_PATH)


PROMPT_PREGRADO = """Analiza el archivo adjunto. El documento es un acta de homologación de PREGRADO.

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


PROMPT_POSGRADO = """Analiza el archivo adjunto. El documento es un acta de homologación de POSGRADO.

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


def inicializar_archivo_prompt(path: Path, contenido_default: str) -> None:
    if not path.exists():
        path.write_text(contenido_default, encoding="utf-8")


def cargar_prompt_persistente(path: Path, contenido_default: str) -> str:
    inicializar_archivo_prompt(path, contenido_default)
    return path.read_text(encoding="utf-8")


def guardar_prompt_persistente(path: Path, contenido: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contenido, encoding="utf-8")



def cargar_modelo_opencode_persistente() -> str:
    """
    Carga el último modelo OpenCode/LLM seleccionado.
    Si el archivo no existe o está vacío, se usará el modelo por defecto.
    """
    try:
        if not MODELO_OPENCODE_PERSISTENTE_PATH.exists():
            return ""

        modelo = MODELO_OPENCODE_PERSISTENTE_PATH.read_text(encoding="utf-8").strip()

        if modelo.lower() == "default opencode":
            return ""

        return modelo
    except Exception:
        return ""


def guardar_modelo_opencode_persistente(modelo: str) -> None:
    """
    Guarda el último modelo seleccionado.
    Modelo vacío significa: usar modelo por defecto de OpenCode.
    """
    try:
        MODELO_OPENCODE_PERSISTENTE_PATH.parent.mkdir(parents=True, exist_ok=True)
        MODELO_OPENCODE_PERSISTENTE_PATH.write_text((modelo or "").strip(), encoding="utf-8")
    except Exception:
        pass


# Inicializa archivos persistentes si todavía no existen
inicializar_archivo_prompt(PROMPT_PREGRADO_PATH, PROMPT_PREGRADO)
inicializar_archivo_prompt(PROMPT_POSGRADO_PATH, PROMPT_POSGRADO)


def reiniciar_app_streamlit() -> None:
    """
    Reinicia la app de forma compatible con versiones recientes y antiguas de Streamlit.
    Se usa para limpiar/reemplazar la tanda de PDFs cargada en el file_uploader.
    """
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


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



PALABRAS_CLAVE_POSGRADO = {
    "maestria",
    "maestría",
    "especializacion",
    "especialización",
    "posgrado",
    "postgrado",
    "master",
    "máster",
    "esp",
}


def quitar_tildes(texto: str) -> str:
    if not isinstance(texto, str):
        return ""
    nfkd = unicodedata.normalize("NFD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def determinar_nivel_academico(texto_documento: str) -> str:
    texto = quitar_tildes(texto_documento or "").lower()

    palabras_normalizadas = {
        quitar_tildes(p).lower()
        for p in PALABRAS_CLAVE_POSGRADO
    }

    for palabra in palabras_normalizadas:
        patron = r"\b" + re.escape(palabra) + r"\b"
        if re.search(patron, texto):
            return "Posgrado"

    return "Pregrado"


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




def limpiar_bloque_codigo(texto: str) -> str:
    """
    Limpia contenido que puede venir desde stdout de OpenCode o desde un .ahk temporal.

    Python se encarga de:
    - Quitar fences markdown.
    - Quitar marcadores de inicio/fin.
    - Preservar solo el código AHK.
    """
    if not texto:
        return ""

    lineas_limpias = []

    for linea in texto.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        linea_strip = linea.strip()

        if linea_strip.startswith("```"):
            continue

        if re.match(r"^---\s*INICIO\s+SCRIPT\s+(AUTOHOTKEY|AHK)\s*---$", linea_strip, re.IGNORECASE):
            continue

        if re.match(r"^---\s*FIN\s+SCRIPT\s+(AUTOHOTKEY|AHK)\s*---$", linea_strip, re.IGNORECASE):
            continue

        lineas_limpias.append(linea.rstrip())

    return "\n".join(lineas_limpias).strip()


def extraer_script_ahk(respuesta: str):
    """
    Extrae código AHK desde la respuesta de OpenCode si viene entre marcadores.
    Si no hay marcadores, solo acepta el texto si parece ser un script AHK.
    """
    if not respuesta:
        return None

    patrones = [
        r"---\s*INICIO\s+SCRIPT\s+AUTOHOTKEY\s*---(.*?)---\s*FIN\s+SCRIPT\s+AUTOHOTKEY\s*---",
        r"---\s*INICIO\s+SCRIPT\s+AHK\s*---(.*?)---\s*FIN\s+SCRIPT\s+AHK\s*---",
    ]

    for patron in patrones:
        match = re.search(patron, respuesta, re.DOTALL | re.IGNORECASE)
        if match:
            script = limpiar_bloque_codigo(match.group(1))
            return script if script else None

    limpio = limpiar_bloque_codigo(respuesta)

    lineas = [linea.strip() for linea in limpio.splitlines() if linea.strip()]
    if not lineas:
        return None

    indicadores_ahk = (
        "#SingleInstance",
        "#NoEnv",
        "SendMode",
        "SetKeyDelay",
        "WinTitle",
        "WinWait",
        "WinActivate",
        "Send,",
    )

    if lineas[0].startswith(indicadores_ahk):
        return limpio

    return None



def limpiar_archivos_temporales_opencode(
    run_outputs_dir: Path | None = None,
    final_ahk_path: Path | None = None,
    opencode_work_dir: Path | None = None,
) -> None:
    """
    Limpia temporales de OpenCode sin borrar AHK finales.

    Para paralelismo seguro:
    - Si opencode_work_dir existe, solo limpia esa carpeta aislada.
    - Si no existe, usa el comportamiento legacy sobre BASE_DIR.
    """
    final_resolved = None
    if final_ahk_path:
        try:
            final_resolved = final_ahk_path.resolve()
        except Exception:
            final_resolved = None

    carpetas_temporales = []

    if opencode_work_dir:
        carpetas_temporales.append(opencode_work_dir)
    else:
        carpetas_temporales.append(BASE_DIR)

        if run_outputs_dir:
            carpetas_temporales.append(run_outputs_dir)

    archivos = []
    nombres_temporales = {
        "homologacion.ahk",
        "script_homologacion.ahk",
        "destino_datos.txt",
    }

    for carpeta in carpetas_temporales:
        try:
            if not carpeta.exists() or not carpeta.is_dir():
                continue

            for nombre in nombres_temporales:
                candidato = carpeta / nombre
                if candidato.exists() and candidato.is_file():
                    archivos.append(candidato)

            for candidato in carpeta.glob("*.ahk"):
                if candidato.is_file():
                    archivos.append(candidato)
        except Exception:
            continue

    for archivo in archivos:
        try:
            if not archivo.exists() or not archivo.is_file():
                continue

            if final_resolved and archivo.resolve() == final_resolved:
                continue

            archivo.unlink()
        except Exception:
            pass


def normalizar_nombre_para_busqueda_ahk(nombre: str) -> str:
    """
    Normaliza nombres para comparar:
    - espacios vs guiones bajos
    - mayúsculas/minúsculas
    - tildes
    - sufijos como _autohotkey
    """
    texto = quitar_tildes(str(nombre or "")).lower()
    texto = re.sub(r"\.ahk$|\.pdf$", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def ahk_corresponde_a_pdf(archivo_ahk: Path, nombre_pdf: str) -> bool:
    """
    Verifica si un AHK temporal parece pertenecer al PDF actual.
    Ejemplo:
    MAYRA LEONOR CARABALI OLAVE_202652.pdf
    puede corresponder a:
    MAYRA_LEONOR_CARABALI_OLAVE_202652_autohotkey.ahk
    """
    esperado = normalizar_nombre_para_busqueda_ahk(Path(nombre_pdf).stem)
    candidato = normalizar_nombre_para_busqueda_ahk(archivo_ahk.stem)

    tokens_esperados = [t for t in esperado.split() if t]
    tokens_candidato = set(candidato.split())

    if not tokens_esperados:
        return False

    return all(token in tokens_candidato for token in tokens_esperados)



def buscar_ahk_creado_por_opencode(
    run_outputs_dir: Path | None = None,
    min_mtime: float = 0.0,
    final_ahk_path: Path | None = None,
    opencode_work_dir: Path | None = None,
    nombre_pdf: str | None = None,
):
    """
    Busca un .ahk creado por OpenCode para el PDF actual.

    Reglas para paralelismo seguro:
    - En el worker aislado acepta cualquier .ahk reciente, porque solo ese PDF escribe ahí.
    - En la raíz del lote solo acepta .ahk cuyo nombre parezca corresponder al PDF actual.
    - Nunca devuelve el AHK final esperado.
    """
    final_resolved = None
    if final_ahk_path:
        try:
            final_resolved = final_ahk_path.resolve()
        except Exception:
            final_resolved = None

    carpetas = []

    if opencode_work_dir:
        carpetas.append(opencode_work_dir)

    if run_outputs_dir:
        carpetas.append(run_outputs_dir)

    if not carpetas:
        carpetas.append(BASE_DIR)

    candidatos = []

    run_outputs_resolved = None
    if run_outputs_dir:
        try:
            run_outputs_resolved = run_outputs_dir.resolve()
        except Exception:
            run_outputs_resolved = None

    opencode_work_resolved = None
    if opencode_work_dir:
        try:
            opencode_work_resolved = opencode_work_dir.resolve()
        except Exception:
            opencode_work_resolved = None

    for carpeta in carpetas:
        try:
            if not carpeta.exists() or not carpeta.is_dir():
                continue

            carpeta_resolved = carpeta.resolve()

            for archivo in carpeta.glob("*.ahk"):
                if not archivo.is_file():
                    continue

                try:
                    archivo_resolved = archivo.resolve()
                except Exception:
                    archivo_resolved = None

                if final_resolved and archivo_resolved == final_resolved:
                    continue

                if archivo.stat().st_mtime < min_mtime:
                    continue

                # Si está en la raíz del lote, debe corresponder al PDF actual.
                if (
                    run_outputs_resolved
                    and carpeta_resolved == run_outputs_resolved
                    and nombre_pdf
                    and not ahk_corresponde_a_pdf(archivo, nombre_pdf)
                ):
                    continue

                # Si está en el worker, es seguro aceptarlo aunque tenga nombre genérico.
                candidatos.append(archivo)

        except Exception:
            continue

    candidatos = sorted(
        candidatos,
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    return candidatos[0] if candidatos else None

def normalizar_contenido_ahk(contenido: str) -> str:
    """
    Devuelve solo código AHK limpio, sin marcadores ni fences.
    """
    if not contenido:
        return ""

    extraido = extraer_script_ahk(contenido)

    if extraido:
        return limpiar_bloque_codigo(extraido).strip()

    return limpiar_bloque_codigo(contenido).strip()

def obtener_modelos_opencode(refresh: bool = False):
    """
    Lista modelos disponibles usando:
    opencode models
    opencode models --refresh

    Devuelve modelos en formato provider/model.
    """
    opencode_path = shutil.which("opencode")

    if not opencode_path:
        return {
            "ok": False,
            "models": [],
            "error": "No se encontró opencode en el PATH.",
            "raw": "",
        }

    comando = [opencode_path, "models"]

    if refresh:
        comando.append("--refresh")

    try:
        proceso = subprocess.run(
            comando,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=180,
        )

        salida = quitar_ansi((proceso.stdout or "") + "\n" + (proceso.stderr or ""))

        candidatos = re.findall(
            r"\b[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.:/@+-]+\b",
            salida,
        )

        modelos = []

        for modelo in candidatos:
            modelo = modelo.strip()

            if modelo.startswith("http"):
                continue

            if modelo not in modelos:
                modelos.append(modelo)

        modelos = sorted(modelos)

        return {
            "ok": proceso.returncode == 0,
            "models": modelos,
            "error": "" if proceso.returncode == 0 else salida,
            "raw": salida,
        }

    except Exception as e:
        return {
            "ok": False,
            "models": [],
            "error": str(e),
            "raw": "",
        }


def nombre_ahk_desde_pdf(nombre_pdf: str) -> str:
    """
    El AHK final se llama exactamente igual que el PDF,
    cambiando únicamente la extensión por .ahk.
    """
    return f"{Path(nombre_pdf).stem}.ahk"


def validar_contenido_ahk_final(contenido: str):
    """
    Valida que el archivo final no conserve marcadores de OpenCode.
    """
    if not contenido or not contenido.strip():
        return False, "El contenido AHK está vacío."

    if re.search(r"---\s*INICIO\s+SCRIPT\s+(AUTOHOTKEY|AHK)\s*---", contenido, re.IGNORECASE):
        return False, "El AHK todavía contiene marcador de inicio."

    if re.search(r"---\s*FIN\s+SCRIPT\s+(AUTOHOTKEY|AHK)\s*---", contenido, re.IGNORECASE):
        return False, "El AHK todavía contiene marcador de fin."

    return True, ""



def ejecutar_opencode(
    prompt: str,
    txt_path: Path,
    modelo_opencode: str = '',
    cwd: Path | None = None,
):
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

    workdir = cwd or BASE_DIR
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        comando = [
            opencode_path,
            "run",
            "--dir",
            str(workdir),
        ]

        if modelo_opencode and modelo_opencode.strip():
            comando.extend(["--model", modelo_opencode.strip()])

        comando.extend([
            prompt,
            "--file",
            str(txt_path),
        ])

        proceso = subprocess.run(
            comando,
            cwd=str(workdir),
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
            "cwd": str(workdir),
        }

    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "error": "OpenCode tardó demasiado y se canceló por timeout.",
            "stdout": quitar_ansi(e.stdout or ""),
            "stderr": quitar_ansi(e.stderr or ""),
            "cwd": str(workdir),
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "cwd": str(workdir),
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





def construir_prompt_json_opencode(prompt_original: str) -> str:
    """
    Convierte cualquier prompt editable del usuario a un contrato técnico estable:
    OpenCode solo analiza y responde JSON. Python genera archivos.
    """
    return f"""CONTRATO TÉCNICO OBLIGATORIO — MODO SOLO JSON

El archivo adjunto es texto extraído de un PDF por LLMWhisperer.
Tu tarea es analizar el contenido y devolver ÚNICAMENTE un objeto JSON válido.

REGLAS OBLIGATORIAS:
1. No crees archivos.
2. No escribas archivos .ahk, .csv, .txt ni ningún otro archivo.
3. No uses herramientas de escritura.
4. No generes script AutoHotkey como texto libre.
5. No uses markdown.
6. No incluyas explicación antes ni después del JSON.
7. Aunque el prompt original pida crear archivos o scripts, ignora esa parte: Python generará los archivos.
8. Debes aplicar las condiciones de parada del prompt original, por ejemplo periodo 2024, programa no permitido o calificaciones inferiores al umbral indicado.
9. Extrae registros solamente de la sección Programa Destino Ibero o Programa Destino. No incluyas Programa de Origen.

FORMATO JSON EXACTO:
{{
  "estado": "ok" o "detenido",
  "motivo_detencion": "",
  "estudiante": "",
  "programa_aspira": "",
  "periodo_academico": "",
  "plan_estudio": "",
  "programa_origen": "",
  "creditos_homologados": "",
  "registros": [
    {{
      "codigo_original": "",
      "letras": "",
      "numeros": "",
      "calificacion": ""
    }}
  ]
}}

REGLAS PARA EL JSON:
- Si todo está permitido, usa "estado": "ok" y llena "registros".
- Si se debe detener, usa "estado": "detenido", explica el motivo en "motivo_detencion" y deja "registros": [].
- En "letras" coloca solo letras del código.
- En "numeros" coloca solo números del código.
- En "calificacion" usa siempre dos decimales como texto, por ejemplo "4.00", "4.20", "3.50".
- Si un dato no aparece claramente, usa "No extraído".
- El JSON debe ser parseable con json.loads en Python.

PROMPT ORIGINAL DEL USUARIO:
{prompt_original}
"""


def obtener_valor_payload(data: dict, claves: list[str], default: str = "No extraído") -> str:
    for clave in claves:
        valor = data.get(clave)
        if valor is None:
            continue

        valor = str(valor).strip()
        if valor:
            return valor

    return default


def extraer_datos_payload_opencode(data: dict) -> dict:
    creditos = obtener_valor_payload(
        data,
        ["creditos_homologados", "creditos", "total_creditos"],
        "0",
    )
    creditos_num = re.search(r"\d+", str(creditos))
    creditos = creditos_num.group(0) if creditos_num else "0"

    return {
        "Nombre": obtener_valor_payload(data, ["estudiante", "nombre_estudiante", "nombre"]),
        "Programa al que aspira": obtener_valor_payload(data, ["programa_aspira", "programa_al_que_aspira"]),
        "Plan": obtener_valor_payload(data, ["plan_estudio", "plan"]),
        "Programa origen": obtener_valor_payload(data, ["programa_origen", "nombre_programa_origen"]),
        "Créditos homologados": creditos,
    }


def limpiar_temporales_raiz_proyecto_opencode() -> None:
    """
    En la arquitectura nueva OpenCode no debe crear archivos.
    Si aun así deja basura en la raíz del proyecto, se elimina.
    """
    patrones = [
        "*.ahk",
        "datos_codigos*.txt",
        "datos_codigos*.csv",
        "destino_ibero*.csv",
        "destino_ibero*.txt",
        "ingresar_homologaciones*.txt",
        "ingresar_homologaciones*.csv",
    ]

    for patron in patrones:
        for archivo in BASE_DIR.glob(patron):
            try:
                if archivo.is_file():
                    archivo.unlink()
            except Exception:
                pass


def detectar_condicion_parada_opencode(respuesta: str) -> str | None:
    """
    Detecta condiciones de parada reales.

    Importante:
    No debe marcar como detenido frases positivas como:
    - Ninguna inferior a 3
    - Todas son 4.5
    - Mínimo 3.2
    - No contiene 2024
    """
    if not respuesta:
        return None

    lineas_relevantes = []

    marcadores_fuertes = [
        "ejecucion detenida",
        "se detuvo la ejecucion",
        "detuve la ejecucion",
        "no se genero el script",
        "no se genero el script de autohotkey",
        "no se genero el archivo de datos",
        "no se genero ningun script",
    ]

    patrones_positivos = [
        r"se\s+encontro\s+.*calificacion.*(inferior|menor|por debajo)\s+a?\s*3",
        r"calificacion\s+detectada.*(inferior|menor|por debajo)\s+a?\s*3",
        r"calificacion.*por\s+debajo\s+de\s+3",
        r"calificacion.*inferior\s+a\s+3",
        r"calificacion.*menor\s+a\s+3",
        r"calificacion\s*=\s*[0-2](?:[\\.,]\\d+)?\\b",
        r"contiene\s+2024",
    ]

    patrones_negativos = [
        "ninguna inferior a 3",
        "ninguna menor a 3",
        "ninguna por debajo de 3",
        "no hay calificacion inferior",
        "no hay calificaciones inferiores",
        "sin calificaciones inferiores",
        "sin calificacion inferior",
        "todas son",
        "todas >= 3",
        "todas ≥ 3",
        "minimo 3",
        "mínimo 3",
        "no contiene 2024",
        "ok, no contiene 2024",
    ]

    for linea in respuesta.splitlines():
        linea_limpia = linea.strip()

        if not linea_limpia:
            continue

        linea_normalizada = quitar_tildes(linea_limpia).lower()

        if any(neg in linea_normalizada for neg in patrones_negativos):
            continue

        es_condicion = False

        if any(marker in linea_normalizada for marker in marcadores_fuertes):
            es_condicion = True

        if not es_condicion:
            for patron in patrones_positivos:
                if re.search(patron, linea_normalizada, re.IGNORECASE):
                    es_condicion = True
                    break

        if es_condicion:
            lineas_relevantes.append(linea_limpia)

        if len(lineas_relevantes) >= 3:
            break

    if not lineas_relevantes:
        return None

    return " | ".join(lineas_relevantes)

def crear_zip_ahk(run_outputs_dir: Path, filas: list | None = None):
    """
    Crea un ZIP solamente con los AHK finales registrados en la tabla.
    No incluye temporales generados por OpenCode.
    """
    ahk_files = []

    if filas:
        for fila in filas:
            ruta = fila.get("Archivo AHK")
            if not ruta or ruta == "No generado":
                continue

            archivo = Path(ruta)

            if archivo.exists() and archivo.is_file():
                ahk_files.append(archivo)
    else:
        ahk_files = sorted(
            p for p in run_outputs_dir.glob("*.ahk")
            if (
                p.is_file()
                and p.name.lower() not in {"homologacion.ahk", "script_homologacion.ahk"}
                and not p.name.lower().endswith("_script.ahk")
            )
        )

    ahk_files = sorted(set(ahk_files), key=lambda p: p.name.lower())

    if not ahk_files:
        return None, []

    zip_path = run_outputs_dir / "scripts_ahk.zip"

    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for ahk_file in ahk_files:
            zipf.write(ahk_file, arcname=ahk_file.name)

    return zip_path, ahk_files

def formatear_duracion(segundos: float | int | None) -> str:
    """
    Convierte segundos a formato mm:ss u hh:mm:ss.
    """
    if segundos is None:
        return "calculando..."

    try:
        segundos = int(max(0, segundos))
    except Exception:
        return "calculando..."

    horas = segundos // 3600
    minutos = (segundos % 3600) // 60
    seg = segundos % 60

    if horas:
        return f"{horas:02d}:{minutos:02d}:{seg:02d}"

    return f"{minutos:02d}:{seg:02d}"


class ArchivoSubidoEnMemoria:
    """
    Copia estable del archivo subido por Streamlit.
    Evita depender directamente del objeto UploadedFile dentro de threads.
    """
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getbuffer(self):
        return self._data


def crear_directorio_worker(worker_root_dir: Path, nombre_pdf: str) -> Path:
    """
    Crea una carpeta aislada para procesar un PDF.
    Esta carpeta será el cwd de OpenCode, para evitar cruces entre procesos.
    """
    stem = Path(sanitizar_nombre_archivo(nombre_pdf)).stem
    stem = re.sub(r'[<>:"/\\|?*]', "", stem)
    stem = stem.replace("\n", " ").replace("\r", " ").strip()
    stem = re.sub(r"\s+", " ", stem) or "documento"

    worker_root_dir.mkdir(parents=True, exist_ok=True)
    worker_dir = worker_root_dir / stem

    if not worker_dir.exists():
        return worker_dir

    sufijo = datetime.now().strftime("%H%M%S_%f")
    return worker_root_dir / f"{stem}__{sufijo}"


def procesar_pdf(
    uploaded_file,
    prompt_pregrado: str,
    prompt_posgrado: str,
    modelo_opencode: str,
    run_uploads_dir: Path,
    run_outputs_dir: Path,
    progress_callback=None,
):
    inicio_pdf = time.time()
    nombre_seguro = sanitizar_nombre_archivo(uploaded_file.name)
    pdf_path = run_uploads_dir / nombre_seguro

    worker_root_dir = run_outputs_dir / "_workers"
    worker_dir = crear_directorio_worker(worker_root_dir, nombre_seguro)
    opencode_work_dir = worker_dir / "opencode_cwd"
    opencode_work_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(nombre_seguro).stem

    txt_path = run_outputs_dir / f"{stem}_llmwhisperer.txt"
    llmwhisperer_json_path = run_outputs_dir / f"{stem}_llmwhisperer_raw.json"
    opencode_txt_path = run_outputs_dir / f"{stem}_opencode.txt"
    opencode_json_path = run_outputs_dir / f"{stem}_opencode.json"
    ahk_path = run_outputs_dir / nombre_ahk_desde_pdf(nombre_seguro)

    fila = {
        "Archivo": nombre_seguro,
        "Estado": "Iniciado",
        "Fase actual": "Iniciado",
        "Duración": "",
        "Worker dir": str(worker_dir),
        "Nivel": "",
        "Prompt usado": "",
        "Modelo OpenCode": modelo_opencode or "Default OpenCode",
        "Nombre": "",
        "Programa al que aspira": "",
        "Plan": "",
        "Programa origen": "",
        "Créditos homologados": "",
        "TXT LLMWhisperer": "",
        "Respuesta OpenCode": "",
        "Archivo AHK": "No generado",
        "Error": "",
    }

    def reportar(fase: str, avance_pdf: float, detalle: str = "") -> None:
        fila["Fase actual"] = fase

        if not progress_callback:
            return

        try:
            avance_pdf = max(0.0, min(1.0, float(avance_pdf)))
            progress_callback(
                fase=fase,
                avance_pdf=avance_pdf,
                detalle=detalle,
            )
        except Exception:
            pass

    reportar("Guardando PDF", 0.03, "Guardando el archivo cargado en la carpeta del lote.")

    with open(pdf_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    reportar("LLMWhisperer", 0.12, "Enviando PDF a LLMWhisperer y esperando la extracción de texto.")

    resultado_parseo = parsear_pdf_con_llmwhisperer(pdf_path)
    guardar_json(llmwhisperer_json_path, resultado_parseo)

    if not resultado_parseo.get("ok"):
        fila["Estado"] = "Error LLMWhisperer"
        fila["Error"] = json.dumps(resultado_parseo, ensure_ascii=False)
        fila["Duración"] = formatear_duracion(time.time() - inicio_pdf)
        reportar("Error LLMWhisperer", 1.0, "LLMWhisperer no pudo extraer el texto del PDF.")
        return fila

    reportar("Guardando TXT", 0.42, "LLMWhisperer respondió. Guardando TXT y JSON.")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(resultado_parseo["text"])

    reportar("Detectando nivel académico", 0.48, "Clasificando el documento como Pregrado o Posgrado.")

    nivel_academico = determinar_nivel_academico(resultado_parseo["text"])
    fila["Nivel"] = nivel_academico

    if nivel_academico == "Posgrado":
        prompt_usado = prompt_posgrado
        fila["Prompt usado"] = "Posgrado"
    else:
        prompt_usado = prompt_pregrado
        fila["Prompt usado"] = "Pregrado"

    fila["TXT LLMWhisperer"] = str(txt_path)

    reportar(
        "Preparando OpenCode",
        0.56,
        f"Nivel detectado: {nivel_academico}. Prompt usado: {fila['Prompt usado']}.",
    )

    limpiar_archivos_temporales_opencode(
        run_outputs_dir=run_outputs_dir,
        final_ahk_path=ahk_path,
        opencode_work_dir=opencode_work_dir,
    )

    reportar(
        "OpenCode CLI",
        0.62,
        f"Ejecutando análisis con OpenCode. Modelo: {modelo_opencode or 'Default OpenCode'}.",
    )

    inicio_opencode = time.time()
    prompt_opencode_json = construir_prompt_json_opencode(prompt_usado)

    resultado_opencode = ejecutar_opencode(
        prompt=prompt_opencode_json,
        txt_path=txt_path,
        modelo_opencode=modelo_opencode,
        cwd=opencode_work_dir,
    )
    guardar_json(opencode_json_path, resultado_opencode)

    reportar("Guardando respuesta OpenCode", 0.82, "OpenCode respondió. Guardando stdout y JSON técnico.")

    respuesta = resultado_opencode.get("stdout", "")

    with open(opencode_txt_path, "w", encoding="utf-8") as f:
        f.write(respuesta)

    fila["Respuesta OpenCode"] = str(opencode_txt_path)

    if not resultado_opencode.get("ok"):
        fila["Estado"] = "Error OpenCode"
        fila["Fase actual"] = "Error OpenCode"
        fila["Error"] = resultado_opencode.get("stderr") or resultado_opencode.get("error", "")
        fila["Duración"] = formatear_duracion(time.time() - inicio_pdf)
        limpiar_temporales_raiz_proyecto_opencode()
        reportar("Error OpenCode", 1.0, "OpenCode devolvió error. Revisa STDERR o el JSON técnico.")
        return fila

    reportar("Interpretando JSON", 0.86, "Validando que OpenCode haya respondido solo JSON estructurado.")

    try:
        payload_opencode = extraer_json_desde_respuesta(respuesta)
        estado_payload, motivo_detencion, registros_payload = validar_payload_opencode(payload_opencode)
    except AhkBuilderError as e:
        fila["Estado"] = "Error JSON OpenCode"
        fila["Fase actual"] = "Error JSON OpenCode"
        fila["Archivo AHK"] = "No generado"
        fila["Error"] = str(e)
        fila["Duración"] = formatear_duracion(time.time() - inicio_pdf)
        limpiar_temporales_raiz_proyecto_opencode()
        reportar("Error JSON OpenCode", 1.0, str(e))
        return fila

    fila.update(extraer_datos_payload_opencode(payload_opencode))

    if estado_payload == "detenido":
        fila["Estado"] = "Detenido por condición"
        fila["Fase actual"] = "Detenido por condición"
        fila["Archivo AHK"] = "No generado"
        fila["Error"] = motivo_detencion or "OpenCode detuvo la ejecución por una condición de negocio."
        fila["Duración"] = formatear_duracion(time.time() - inicio_pdf)
        limpiar_temporales_raiz_proyecto_opencode()
        reportar("Detenido por condición", 1.0, fila["Error"])
        return fila

    reportar("Generando AHK con Python", 0.92, "Python generará el script AHK final desde los registros JSON.")

    try:
        script_ahk_final = generar_script_ahk_desde_registros(
            registros_payload,
            nivel_academico=nivel_academico,
        )
        es_valido, error_validacion = validar_contenido_ahk_final(script_ahk_final)

        if not es_valido:
            raise AhkBuilderError(error_validacion)

        with open(ahk_path, "w", encoding="utf-8") as f:
            f.write(script_ahk_final.strip() + "\n")

        fila["Archivo AHK"] = str(ahk_path)

    except AhkBuilderError as e:
        fila["Estado"] = "Error AHK Python"
        fila["Fase actual"] = "Error AHK Python"
        fila["Archivo AHK"] = "No generado"
        fila["Error"] = str(e)
        fila["Duración"] = formatear_duracion(time.time() - inicio_pdf)
        limpiar_temporales_raiz_proyecto_opencode()
        reportar("Error AHK Python", 1.0, str(e))
        return fila

    limpiar_archivos_temporales_opencode(
        run_outputs_dir=run_outputs_dir,
        final_ahk_path=ahk_path,
        opencode_work_dir=opencode_work_dir,
    )
    limpiar_temporales_raiz_proyecto_opencode()

    fila["Estado"] = "Completado"
    fila["Fase actual"] = "Completado"
    fila["Duración"] = formatear_duracion(time.time() - inicio_pdf)

    reportar("Completado", 1.0, "PDF procesado correctamente. AHK generado por Python.")

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

st.header("1. Editar prompts para OpenCode")

st.write(
    "La app detectará automáticamente si cada PDF es de Pregrado o Posgrado y usará el prompt correspondiente."
)

tab_pregrado, tab_posgrado = st.tabs(["Prompt Pregrado", "Prompt Posgrado"])

with tab_pregrado:
    prompt_pregrado = st.text_area(
        "Este prompt se usará cuando el PDF sea detectado como Pregrado.",
        value=cargar_prompt_persistente(PROMPT_PREGRADO_PATH, PROMPT_PREGRADO),
        height=340,
        key="prompt_pregrado",
    )

with tab_posgrado:
    prompt_posgrado = st.text_area(
        "Este prompt se usará cuando el PDF sea detectado como Posgrado.",
        value=cargar_prompt_persistente(PROMPT_POSGRADO_PATH, PROMPT_POSGRADO),
        height=340,
        key="prompt_posgrado",
    )

col_guardar_1, col_guardar_2 = st.columns([1, 3])

with col_guardar_1:
    if st.button("💾 Guardar prompts"):
        guardar_prompt_persistente(PROMPT_PREGRADO_PATH, prompt_pregrado)
        guardar_prompt_persistente(PROMPT_POSGRADO_PATH, prompt_posgrado)
        st.success("✅ Prompts guardados correctamente")

with col_guardar_2:
    st.caption(f"Los prompts se guardan en: {PROMPTS_DIR}")

st.header("2. Seleccionar modelo de OpenCode")

if "modelos_opencode_resultado" not in st.session_state:
    st.session_state.modelos_opencode_resultado = obtener_modelos_opencode(refresh=False)

col_modelo_1, col_modelo_2 = st.columns([1, 3])

with col_modelo_1:
    if st.button("🔄 Actualizar modelos"):
        with st.spinner("Consultando modelos con opencode models --refresh..."):
            st.session_state.modelos_opencode_resultado = obtener_modelos_opencode(refresh=True)

modelos_resultado = st.session_state.modelos_opencode_resultado
modelos_detectados = modelos_resultado.get("models", [])

opcion_default_modelo = "Usar modelo por defecto de OpenCode"

opciones_modelo = [opcion_default_modelo] + modelos_detectados

modelo_guardado_previo = cargar_modelo_opencode_persistente()

indice_modelo_guardado = 0
modelo_manual_guardado = ""

if modelo_guardado_previo:
    if modelo_guardado_previo in opciones_modelo:
        indice_modelo_guardado = opciones_modelo.index(modelo_guardado_previo)
    else:
        modelo_manual_guardado = modelo_guardado_previo

modelo_seleccionado_ui = st.selectbox(
    "Modelo detectado por OpenCode",
    options=opciones_modelo,
    index=indice_modelo_guardado,
    key="modelo_detectado_opencode",
)

modelo_manual = st.text_input(
    "O escribe manualmente un modelo en formato provider/model",
    value=modelo_manual_guardado,
    placeholder="Ejemplo: opencode/deepseek-v4-flash-free",
    key="modelo_manual_opencode",
)

if modelo_manual.strip():
    modelo_opencode = modelo_manual.strip()
else:
    modelo_opencode = "" if modelo_seleccionado_ui == opcion_default_modelo else modelo_seleccionado_ui

if modelo_opencode != modelo_guardado_previo:
    guardar_modelo_opencode_persistente(modelo_opencode)

if modelo_opencode:
    st.success(f"✅ Modelo seleccionado: {modelo_opencode}")
else:
    st.info("Se usará el modelo por defecto de OpenCode.")

st.caption(f"Último modelo recordado en: {MODELO_OPENCODE_PERSISTENTE_PATH}")

if not modelos_resultado.get("ok"):
    with st.expander("Ver error al listar modelos OpenCode"):
        st.text_area(
            "Salida de opencode models",
            value=modelos_resultado.get("error", "") or modelos_resultado.get("raw", ""),
            height=200,
        )

st.header("3. Seleccionar PDFs")

if "pdf_uploader_version" not in st.session_state:
    st.session_state["pdf_uploader_version"] = 0

col_upload_1, col_upload_2 = st.columns([3, 1])

with col_upload_1:
    uploaded_files = st.file_uploader(
        "Selecciona uno o varios archivos PDF",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"pdf_uploader_{st.session_state['pdf_uploader_version']}",
    )

with col_upload_2:
    st.write("")
    st.write("")
    if st.button(
        "🧹 Reemplazar tanda",
        help="Limpia los PDFs cargados actualmente para seleccionar una nueva tanda sin quitar archivo por archivo.",
        key="boton_reemplazar_tanda_pdfs",
    ):
        st.session_state["pdf_uploader_version"] += 1
        reiniciar_app_streamlit()

st.caption(
    "Para procesar otra tanda, usa **🧹 Reemplazar tanda** y luego selecciona los nuevos PDFs. "
    "Esto no borra los resultados del último procesamiento."
)

if uploaded_files:
    st.info(f"📚 PDFs seleccionados: {len(uploaded_files)}")

    with st.expander("Ver archivos seleccionados", expanded=False):
        for file in uploaded_files:
            st.write(f"- {file.name} ({len(file.getvalue())} bytes)")

st.header("4. Configurar procesamiento paralelo")

if uploaded_files:
    max_workers_limite = min(6, len(uploaded_files))
else:
    max_workers_limite = 1

if not uploaded_files:
    max_workers_opencode = 1
    st.info("Selecciona PDFs para configurar el procesamiento paralelo.")
elif max_workers_limite <= 1:
    max_workers_opencode = 1
    st.info("Hay 1 PDF seleccionado. Se usará concurrencia = 1.")
else:
    max_workers_default = min(2, max_workers_limite)

    max_workers_opencode = st.slider(
        "Número de PDFs en paralelo",
        min_value=1,
        max_value=max_workers_limite,
        value=max_workers_default,
        step=1,
    )

st.caption(
    "Recomendación inicial: usa 2 PDFs en paralelo. Luego prueba 3 o 4 y valida estabilidad, tiempos y errores."
)


def es_estado_error_reintentable(estado: str) -> bool:
    """
    Define qué filas se pueden reintentar.

    Se consideran reintentables los errores técnicos del flujo:
    - Error LLMWhisperer
    - Error OpenCode
    - Error JSON OpenCode
    - Error AHK Python
    - Error inesperado

    No se reintenta:
    - Completado
    - Detenido por condición, porque es una condición de negocio detectada.
    """
    texto = quitar_tildes(str(estado or "")).lower().strip()

    if not texto:
        return False

    if "completado" in texto:
        return False

    if "detenido" in texto:
        return False

    return "error" in texto or "fall" in texto or "inesperado" in texto


def obtener_filas_con_error(filas: list[dict]) -> list[dict]:
    return [fila for fila in filas if es_estado_error_reintentable(fila.get("Estado", ""))]


def cargar_pdf_jobs_desde_lote(run_id: str, filas_error: list[dict]) -> tuple[list[ArchivoSubidoEnMemoria], list[str]]:
    """
    Reconstruye los PDF originales desde uploads/<run_id>/ para permitir reintentos
    incluso si el widget de subida ya no tiene los archivos en memoria.
    """
    jobs = []
    no_encontrados = []
    run_uploads_dir = UPLOADS_DIR / run_id

    for fila in filas_error:
        nombre_archivo = sanitizar_nombre_archivo(fila.get("Archivo", ""))
        pdf_path = run_uploads_dir / nombre_archivo

        if not nombre_archivo or not pdf_path.exists() or not pdf_path.is_file():
            no_encontrados.append(nombre_archivo or "Archivo sin nombre")
            continue

        try:
            jobs.append(ArchivoSubidoEnMemoria(nombre_archivo, pdf_path.read_bytes()))
        except Exception:
            no_encontrados.append(nombre_archivo)

    return jobs, no_encontrados


def normalizar_clave_archivo_resultado(nombre_archivo: str) -> str:
    """
    Crea una clave estable para identificar el mismo PDF entre el primer lote y sus reintentos.

    El problema que se corrige aquí es que un reintento genera un lote nuevo; por eso,
    si no fusionamos por nombre de archivo, Streamlit termina mostrando solo el lote
    del reintento y desaparecen de la vista los AHK correctos del primer intento.
    """
    nombre = sanitizar_nombre_archivo(str(nombre_archivo or ""))
    nombre = quitar_tildes(nombre).lower().strip()
    nombre = re.sub(r"\s+", " ", nombre)
    return nombre


def fusionar_filas_resultado(
    filas_base: list[dict],
    filas_reintento: list[dict],
) -> list[dict]:
    """
    Fusiona el resultado histórico con el resultado de un reintento.

    Reglas:
    - Las filas que NO fueron reintentadas se conservan intactas.
    - Las filas que SÍ fueron reintentadas se reemplazan por su resultado más reciente.
    - Si por alguna razón aparece un archivo nuevo en el reintento, se agrega al final.

    Esto mantiene visibles los PDF completados y sus AHK generados en el primer intento,
    pero actualiza los PDF que antes estaban en error.
    """
    filas_base = filas_base or []
    filas_reintento = filas_reintento or []

    reintentos_por_archivo = {}

    for fila in filas_reintento:
        clave = normalizar_clave_archivo_resultado(fila.get("Archivo", ""))
        if clave:
            reintentos_por_archivo[clave] = fila

    filas_combinadas = []
    claves_usadas = set()

    for fila_base in filas_base:
        clave = normalizar_clave_archivo_resultado(fila_base.get("Archivo", ""))

        if clave and clave in reintentos_por_archivo:
            filas_combinadas.append(reintentos_por_archivo[clave])
            claves_usadas.add(clave)
        else:
            filas_combinadas.append(fila_base)

    for fila_reintento in filas_reintento:
        clave = normalizar_clave_archivo_resultado(fila_reintento.get("Archivo", ""))

        if clave and clave in claves_usadas:
            continue

        filas_combinadas.append(fila_reintento)

    return filas_combinadas


def guardar_artifactos_resultado_lote(
    run_outputs_dir: Path,
    filas: list[dict],
) -> tuple[Path, list[dict], Path | None, Path | None, list[Path]]:
    """
    Regenera CSV, CSV de errores y ZIP AHK a partir de una tabla de resultados.

    Se usa especialmente después de un reintento, porque el resultado mostrado debe ser
    acumulado: filas correctas del primer intento + filas actualizadas del reintento.
    """
    run_outputs_dir.mkdir(parents=True, exist_ok=True)

    resumen_csv_path = run_outputs_dir / "resumen_resultados.csv"
    guardar_csv_resumen(resumen_csv_path, filas)

    filas_error = obtener_filas_con_error(filas)
    errores_csv_path = run_outputs_dir / "resumen_errores_reintentables.csv"

    if filas_error:
        guardar_csv_resumen(errores_csv_path, filas_error)
    elif errores_csv_path.exists():
        try:
            errores_csv_path.unlink()
        except Exception:
            pass

    zip_ahk_path, archivos_ahk = crear_zip_ahk(run_outputs_dir, filas)

    zip_final_path = run_outputs_dir / "scripts_ahk.zip"
    if not zip_ahk_path and zip_final_path.exists():
        try:
            zip_final_path.unlink()
        except Exception:
            pass

    return (
        resumen_csv_path,
        filas_error,
        errores_csv_path if filas_error else None,
        zip_ahk_path,
        archivos_ahk,
    )


def reconstruir_resultado_lote_combinado(
    resultado_base: dict,
    resultado_reintento: dict,
) -> dict:
    """
    Construye el resultado acumulado después de un reintento.

    Antes, el reintento reemplazaba `ultimo_lote` completo por un lote que contenía
    solo los PDF reintentados. Eso hacía que desaparecieran de la UI:
    - las filas correctas del primer intento,
    - el ZIP con los AHK correctos del primer intento,
    - y los botones de descarga asociados.

    Ahora se conserva el lote base y solo se reemplazan las filas de los archivos
    que fueron reintentados. Luego se regeneran el CSV y el ZIP con TODOS los AHK
    disponibles en la tabla combinada.
    """
    filas_base = resultado_base.get("filas") or []
    filas_reintento = resultado_reintento.get("filas") or []
    filas_combinadas = fusionar_filas_resultado(filas_base, filas_reintento)

    run_id = resultado_reintento.get("run_id", "")
    run_outputs_dir = Path(resultado_reintento.get("run_outputs_dir") or RUNS_DIR / run_id)

    (
        resumen_csv_path,
        filas_error,
        errores_csv_path,
        zip_ahk_path,
        archivos_ahk,
    ) = guardar_artifactos_resultado_lote(run_outputs_dir, filas_combinadas)

    metadata_combinada_path = run_outputs_dir / "metadata_resultado_combinado.json"
    guardar_json(metadata_combinada_path, {
        "run_id": run_id,
        "tipo_lote": "Resultado combinado con reintentos",
        "run_id_base": resultado_base.get("run_id", ""),
        "run_id_reintento": resultado_reintento.get("run_id", ""),
        "parent_run_id": resultado_reintento.get("parent_run_id", ""),
        "total_filas_base": len(filas_base),
        "total_filas_reintento": len(filas_reintento),
        "total_filas_combinadas": len(filas_combinadas),
        "errores_reintentables_restantes": len(filas_error),
        "ahk_en_zip": len(archivos_ahk),
        "fecha": datetime.now().isoformat(timespec="seconds"),
    })

    return {
        "run_id": run_id,
        "parent_run_id": resultado_base.get("run_id", ""),
        "run_uploads_dir": resultado_reintento.get("run_uploads_dir", ""),
        "run_outputs_dir": str(run_outputs_dir),
        "filas": filas_combinadas,
        "filas_error": filas_error,
        "resumen_csv_path": str(resumen_csv_path),
        "errores_csv_path": str(errores_csv_path) if errores_csv_path else "",
        "zip_ahk_path": str(zip_ahk_path) if zip_ahk_path else "",
        "es_resultado_combinado": True,
        "metadata_combinada_path": str(metadata_combinada_path),
    }


def ejecutar_lote_streamlit(
    pdf_jobs: list[ArchivoSubidoEnMemoria],
    prompt_pregrado: str,
    prompt_posgrado: str,
    modelo_opencode: str,
    max_workers_opencode: int,
    etiqueta_boton: str = "Procesamiento",
    parent_run_id: str | None = None,
) -> dict:
    """
    Ejecuta un lote completo y renderiza progreso en Streamlit.
    Sirve tanto para el primer procesamiento como para los reintentos.
    """
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_uploads_dir = UPLOADS_DIR / run_id
    run_outputs_dir = RUNS_DIR / run_id

    run_uploads_dir.mkdir(parents=True, exist_ok=True)
    run_outputs_dir.mkdir(parents=True, exist_ok=True)

    prompt_pregrado_path = run_outputs_dir / "prompt_pregrado.txt"
    prompt_posgrado_path = run_outputs_dir / "prompt_posgrado.txt"
    modelo_opencode_path = run_outputs_dir / "modelo_opencode.txt"
    concurrencia_path = run_outputs_dir / "concurrencia.txt"
    metadata_path = run_outputs_dir / "metadata_lote.json"

    with open(prompt_pregrado_path, "w", encoding="utf-8") as f:
        f.write(prompt_pregrado)

    with open(prompt_posgrado_path, "w", encoding="utf-8") as f:
        f.write(prompt_posgrado)

    with open(modelo_opencode_path, "w", encoding="utf-8") as f:
        f.write(modelo_opencode or "Default OpenCode")

    with open(concurrencia_path, "w", encoding="utf-8") as f:
        f.write(str(max_workers_opencode))

    guardar_json(metadata_path, {
        "run_id": run_id,
        "tipo_lote": etiqueta_boton,
        "parent_run_id": parent_run_id or "",
        "total_archivos": len(pdf_jobs),
        "modelo_opencode": modelo_opencode or "Default OpenCode",
        "concurrencia": max_workers_opencode,
        "fecha": datetime.now().isoformat(timespec="seconds"),
    })

    st.info(f"📁 Carpeta de salida del lote: `{run_outputs_dir}`")

    progress = st.progress(0)
    fase_progress = st.progress(0)
    status_placeholder = st.empty()
    metrics_placeholder = st.empty()
    table_placeholder = st.empty()

    total = len(pdf_jobs)
    inicio_lote = time.time()

    eventos_progreso = Queue()
    filas_por_indice = {}
    estado_por_indice = {}

    for index, job in enumerate(pdf_jobs, start=1):
        estado_por_indice[index] = {
            "Archivo": job.name,
            "Estado": "Pendiente",
            "Fase actual": "Pendiente",
            "Avance PDF": "0%",
            "Duración": "",
            "Detalle": "",
            "Archivo AHK": "No generado",
            "Error": "",
        }

    def crear_callback(index: int, nombre_archivo: str):
        def _callback(fase: str, avance_pdf: float, detalle: str = ""):
            eventos_progreso.put({
                "index": index,
                "archivo": nombre_archivo,
                "fase": fase,
                "avance_pdf": avance_pdf,
                "detalle": detalle,
                "ts": time.time(),
            })

        return _callback

    def renderizar_estado():
        avances = []

        for index in range(1, total + 1):
            estado = estado_por_indice.get(index, {})
            avance_texto = estado.get("Avance PDF", "0%").replace("%", "")

            try:
                avances.append(float(avance_texto) / 100)
            except Exception:
                avances.append(0.0)

        progreso_total = sum(avances) / total if total else 0
        completados = sum(
            1 for fila in filas_por_indice.values()
            if fila.get("Estado") == "Completado"
        )
        terminados = len(filas_por_indice)
        errores = sum(
            1 for fila in filas_por_indice.values()
            if es_estado_error_reintentable(fila.get("Estado", ""))
        )

        tiempo_transcurrido = time.time() - inicio_lote
        tiempo_restante = None

        if progreso_total > 0.01:
            tiempo_estimado_total = tiempo_transcurrido / progreso_total
            tiempo_restante = max(0, tiempo_estimado_total - tiempo_transcurrido)

        progress.progress(min(1.0, progreso_total))
        fase_progress.progress(min(1.0, terminados / total if total else 0))

        activos = [
            estado for estado in estado_por_indice.values()
            if estado.get("Estado") == "Procesando"
        ]

        if activos:
            activos_txt = "\n".join(
                f"- **{a.get('Archivo')}** → {a.get('Fase actual')} ({a.get('Avance PDF')})"
                for a in activos[:6]
            )
        else:
            activos_txt = "No hay PDFs activos en este instante."

        status_placeholder.info(
            f"🚀 {etiqueta_boton} activo\n\n"
            f"**PDFs en paralelo configurados:** {max_workers_opencode}\n\n"
            f"**Activos:**\n{activos_txt}"
        )

        metrics_placeholder.markdown(
            f"""
**Progreso total:** {progreso_total * 100:.1f}%  
**Terminados:** {terminados}/{total}  
**Completados:** {completados}  
**Errores reintentables:** {errores}  
**Tiempo transcurrido:** {formatear_duracion(tiempo_transcurrido)}  
**Tiempo restante estimado:** {formatear_duracion(tiempo_restante)}
"""
        )

        filas_estado = [
            estado_por_indice[index]
            for index in sorted(estado_por_indice)
        ]

        table_placeholder.dataframe(filas_estado, use_container_width=True)

    def consumir_eventos_progreso():
        while True:
            try:
                evento = eventos_progreso.get_nowait()
            except Empty:
                break

            index = evento["index"]
            avance_pdf = max(0.0, min(1.0, float(evento.get("avance_pdf") or 0)))

            estado = estado_por_indice[index]
            estado["Estado"] = "Procesando"
            estado["Fase actual"] = evento.get("fase", "")
            estado["Avance PDF"] = f"{avance_pdf * 100:.0f}%"
            estado["Detalle"] = evento.get("detalle", "")

    def ejecutar_job(index: int, job: ArchivoSubidoEnMemoria):
        return procesar_pdf(
            uploaded_file=job,
            prompt_pregrado=prompt_pregrado,
            prompt_posgrado=prompt_posgrado,
            modelo_opencode=modelo_opencode,
            run_uploads_dir=run_uploads_dir,
            run_outputs_dir=run_outputs_dir,
            progress_callback=crear_callback(index, job.name),
        )

    renderizar_estado()

    workers = max(1, min(int(max_workers_opencode or 1), total or 1))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futuros = {
            executor.submit(ejecutar_job, index, job): (index, job.name, time.time())
            for index, job in enumerate(pdf_jobs, start=1)
        }

        while futuros:
            consumir_eventos_progreso()

            done, _ = wait(
                list(futuros.keys()),
                timeout=0.5,
                return_when=FIRST_COMPLETED,
            )

            for futuro in done:
                index, nombre_archivo, inicio_archivo = futuros.pop(futuro)

                try:
                    fila = futuro.result()
                except Exception as e:
                    fila = {
                        "Archivo": nombre_archivo,
                        "Estado": "Error inesperado",
                        "Fase actual": "Error inesperado",
                        "Duración": formatear_duracion(time.time() - inicio_archivo),
                        "Worker dir": "No creado",
                        "Nivel": "",
                        "Prompt usado": "",
                        "Modelo OpenCode": modelo_opencode or "Default OpenCode",
                        "Nombre": "",
                        "Programa al que aspira": "",
                        "Plan": "",
                        "Programa origen": "",
                        "Créditos homologados": "",
                        "TXT LLMWhisperer": "",
                        "Respuesta OpenCode": "",
                        "Archivo AHK": "No generado",
                        "Error": str(e) + "\n" + traceback.format_exc(),
                    }

                filas_por_indice[index] = fila

                estado_por_indice[index].update({
                    "Estado": fila.get("Estado", "Finalizado"),
                    "Fase actual": fila.get("Fase actual", "Finalizado"),
                    "Avance PDF": "100%",
                    "Duración": fila.get("Duración", ""),
                    "Detalle": f"Estado final: {fila.get('Estado', 'Desconocido')}",
                    "Archivo AHK": fila.get("Archivo AHK", "No generado"),
                    "Error": fila.get("Error", ""),
                })

            renderizar_estado()

    consumir_eventos_progreso()
    renderizar_estado()

    filas = [
        filas_por_indice[index]
        for index in sorted(filas_por_indice)
    ]

    resumen_csv_path = run_outputs_dir / "resumen_resultados.csv"
    guardar_csv_resumen(resumen_csv_path, filas)

    filas_error = obtener_filas_con_error(filas)
    errores_csv_path = None

    if filas_error:
        errores_csv_path = run_outputs_dir / "resumen_errores_reintentables.csv"
        guardar_csv_resumen(errores_csv_path, filas_error)

    zip_ahk_path, archivos_ahk = crear_zip_ahk(run_outputs_dir, filas)

    status_placeholder.success(f"✅ {etiqueta_boton} finalizado")

    completados = sum(1 for f in filas if f.get("Estado") == "Completado")
    detenidos = sum(1 for f in filas if "detenido" in quitar_tildes(str(f.get("Estado", ""))).lower())
    errores = len(filas_error)

    col_ok, col_error, col_detenido, col_total = st.columns(4)
    col_ok.metric("Completados", completados)
    col_error.metric("Errores reintentables", errores)
    col_detenido.metric("Detenidos", detenidos)
    col_total.metric("Total", total)

    st.subheader("Resumen final")
    st.dataframe(filas, use_container_width=True)

    if filas_error:
        st.subheader("Archivos con error que se pueden reintentar")
        st.dataframe(filas_error, use_container_width=True)
    else:
        st.success("✅ No quedaron archivos con error reintentable en este lote.")

    with open(resumen_csv_path, "rb") as f:
        st.download_button(
            label="⬇️ Descargar CSV de resultados",
            data=f,
            file_name="resumen_resultados.csv",
            mime="text/csv",
            key=f"download_csv_{run_id}",
        )

    if errores_csv_path and errores_csv_path.exists():
        with open(errores_csv_path, "rb") as f:
            st.download_button(
                label="⬇️ Descargar CSV solo de errores reintentables",
                data=f,
                file_name="resumen_errores_reintentables.csv",
                mime="text/csv",
                key=f"download_error_csv_{run_id}",
            )

    if zip_ahk_path and zip_ahk_path.exists():
        with open(zip_ahk_path, "rb") as f:
            st.download_button(
                label=f"⬇️ Descargar scripts AHK en ZIP ({len(archivos_ahk)})",
                data=f,
                file_name="scripts_ahk.zip",
                mime="application/zip",
                key=f"download_zip_{run_id}",
            )

        st.write(f"**ZIP AHK generado:** `{zip_ahk_path}`")
    else:
        st.warning("No se generaron archivos AHK en este lote, por eso no hay ZIP para descargar.")

    st.write(f"**Prompt Pregrado:** `{prompt_pregrado_path}`")
    st.write(f"**Prompt Posgrado:** `{prompt_posgrado_path}`")
    st.write(f"**Modelo OpenCode:** `{modelo_opencode_path}`")
    st.write(f"**Concurrencia usada:** `{concurrencia_path}`")
    st.write(f"**CSV generado:** `{resumen_csv_path}`")

    if errores_csv_path:
        st.write(f"**CSV errores reintentables:** `{errores_csv_path}`")

    st.write(f"**Metadata lote:** `{metadata_path}`")
    st.write(f"**Carpeta completa del lote:** `{run_outputs_dir}`")

    resultado_lote = {
        "run_id": run_id,
        "parent_run_id": parent_run_id or "",
        "run_uploads_dir": str(run_uploads_dir),
        "run_outputs_dir": str(run_outputs_dir),
        "filas": filas,
        "filas_error": filas_error,
        "resumen_csv_path": str(resumen_csv_path),
        "errores_csv_path": str(errores_csv_path) if errores_csv_path else "",
        "zip_ahk_path": str(zip_ahk_path) if zip_ahk_path else "",
    }

    st.session_state["ultimo_lote"] = resultado_lote

    return resultado_lote


def renderizar_resultado_lote_guardado(resultado_lote: dict | None) -> None:
    """
    Vuelve a mostrar el resultado del último lote guardado en session_state.

    Esto evita que la vista de resultados desaparezca cuando Streamlit hace rerun
    después de presionar un botón de descarga.
    """
    if not resultado_lote:
        return

    run_id = resultado_lote.get("run_id", "")
    filas = resultado_lote.get("filas") or []
    filas_error = resultado_lote.get("filas_error") or obtener_filas_con_error(filas)
    run_outputs_dir = resultado_lote.get("run_outputs_dir", "")
    resumen_csv_path = resultado_lote.get("resumen_csv_path", "")
    errores_csv_path = resultado_lote.get("errores_csv_path", "")
    zip_ahk_path = resultado_lote.get("zip_ahk_path", "")

    if not filas:
        return

    total = len(filas)
    completados = sum(1 for f in filas if f.get("Estado") == "Completado")
    detenidos = sum(
        1
        for f in filas
        if "detenido" in quitar_tildes(str(f.get("Estado", ""))).lower()
    )
    errores = len(filas_error)
    ahk_generados = sum(
        1
        for f in filas
        if f.get("Archivo AHK") and f.get("Archivo AHK") != "No generado"
    )

    st.header("7. Resultado del último procesamiento")
    if resultado_lote.get("es_resultado_combinado"):
        st.success(
            "✅ Resultado acumulado después de reintentos: esta tabla conserva los archivos correctos "
            "de intentos anteriores y actualiza solo los PDF reintentados."
        )
    else:
        st.info(
            f"Esta vista queda guardada aunque descargues archivos o limpies la tanda de PDFs. "
            f"Último lote: `{run_id}`"
        )

    col_ok, col_error, col_detenido, col_ahk, col_total = st.columns(5)
    col_ok.metric("Completados", completados)
    col_error.metric("Errores reintentables", errores)
    col_detenido.metric("Detenidos", detenidos)
    col_ahk.metric("AHK generados", ahk_generados)
    col_total.metric("Total", total)

    st.subheader("Resumen final")
    st.dataframe(filas, use_container_width=True)

    if filas_error:
        st.subheader("Archivos con error que se pueden reintentar")
        st.dataframe(filas_error, use_container_width=True)
    else:
        st.success("✅ No quedaron archivos con error reintentable en este lote.")

    def boton_descarga_archivo(path_str: str, label: str, file_name: str, mime: str, key_suffix: str) -> None:
        if not path_str:
            return

        path = Path(path_str)

        if not path.exists() or not path.is_file():
            st.warning(f"No se encontró el archivo para descargar: `{path}`")
            return

        with open(path, "rb") as f:
            st.download_button(
                label=label,
                data=f,
                file_name=file_name,
                mime=mime,
                key=f"persistente_{key_suffix}_{run_id}",
            )

    col_down_1, col_down_2, col_down_3 = st.columns(3)

    with col_down_1:
        boton_descarga_archivo(
            resumen_csv_path,
            "⬇️ Descargar CSV de resultados",
            "resumen_resultados.csv",
            "text/csv",
            "csv_resultados",
        )

    with col_down_2:
        if errores_csv_path:
            boton_descarga_archivo(
                errores_csv_path,
                "⬇️ Descargar CSV solo de errores",
                "resumen_errores_reintentables.csv",
                "text/csv",
                "csv_errores",
            )
        else:
            st.caption("No hay CSV de errores porque no hubo errores reintentables.")

    with col_down_3:
        if zip_ahk_path:
            boton_descarga_archivo(
                zip_ahk_path,
                "⬇️ Descargar scripts AHK en ZIP",
                "scripts_ahk.zip",
                "application/zip",
                "zip_ahk",
            )
        else:
            st.caption("No hay ZIP AHK porque no se generaron scripts en este lote.")

    st.write(f"**Carpeta completa del lote:** `{run_outputs_dir}`")
    st.write(f"**CSV generado:** `{resumen_csv_path}`")

    if errores_csv_path:
        st.write(f"**CSV errores reintentables:** `{errores_csv_path}`")

    if zip_ahk_path:
        st.write(f"**ZIP AHK generado:** `{zip_ahk_path}`")


lote_ejecutado_en_esta_corrida = False

st.header("5. Ejecutar procesamiento completo")

disabled = not uploaded_files or not prompt_pregrado.strip() or not prompt_posgrado.strip() or not api_keys or not opencode_path

if st.button("🚀 Procesar PDFs con LLMWhisperer + OpenCode", disabled=disabled):
    pdf_jobs = [
        ArchivoSubidoEnMemoria(file.name, file.getvalue())
        for file in uploaded_files
    ]

    ejecutar_lote_streamlit(
        pdf_jobs=pdf_jobs,
        prompt_pregrado=prompt_pregrado,
        prompt_posgrado=prompt_posgrado,
        modelo_opencode=modelo_opencode,
        max_workers_opencode=max_workers_opencode,
        etiqueta_boton="Procesamiento por lote",
    )
    lote_ejecutado_en_esta_corrida = True

st.header("6. Reintentar solo PDFs con error")

ultimo_lote = st.session_state.get("ultimo_lote")

if not ultimo_lote:
    st.info("Después de ejecutar un lote, aquí aparecerán los archivos que quedaron con error para poder reintentarlos.")
else:
    filas_error = ultimo_lote.get("filas_error", [])
    run_id_anterior = ultimo_lote.get("run_id", "")

    if not filas_error:
        st.success("✅ El último lote no tiene archivos con error reintentable.")
    else:
        st.warning(
            f"Se encontraron {len(filas_error)} archivo(s) con error reintentable en el lote `{run_id_anterior}`."
        )
        st.dataframe(filas_error, use_container_width=True)

        max_workers_retry_limite = min(max_workers_opencode, len(filas_error)) if filas_error else 1
        max_workers_retry_limite = max(1, max_workers_retry_limite)

        concurrencia_reintento = st.slider(
            "Número de PDFs en paralelo para el reintento",
            min_value=1,
            max_value=max_workers_retry_limite,
            value=max_workers_retry_limite,
            step=1,
            key=f"concurrencia_reintento_{run_id_anterior}",
        )

        if st.button(
            f"🔁 Reintentar solo los {len(filas_error)} PDF(s) con error",
            disabled=not api_keys or not opencode_path,
            key=f"boton_reintentar_{run_id_anterior}",
        ):
            pdf_jobs_retry, no_encontrados = cargar_pdf_jobs_desde_lote(run_id_anterior, filas_error)

            if no_encontrados:
                st.error(
                    "No se pudieron encontrar estos PDFs originales para reintentar: "
                    + ", ".join(no_encontrados)
                )

            if pdf_jobs_retry:
                # Guardamos una copia del lote visible antes del reintento.
                # `ejecutar_lote_streamlit` crea un lote nuevo solo con los PDF reintentados,
                # pero la vista final debe conservar también los PDF correctos del primer intento.
                resultado_base_antes_reintento = dict(ultimo_lote)

                resultado_reintento = ejecutar_lote_streamlit(
                    pdf_jobs=pdf_jobs_retry,
                    prompt_pregrado=prompt_pregrado,
                    prompt_posgrado=prompt_posgrado,
                    modelo_opencode=modelo_opencode,
                    max_workers_opencode=concurrencia_reintento,
                    etiqueta_boton="Reintento de errores",
                    parent_run_id=run_id_anterior,
                )

                resultado_combinado = reconstruir_resultado_lote_combinado(
                    resultado_base=resultado_base_antes_reintento,
                    resultado_reintento=resultado_reintento,
                )

                st.session_state["ultimo_lote"] = resultado_combinado

                st.success(
                    "✅ Resultado combinado actualizado: se conservaron los AHK y las filas correctas "
                    "del primer intento, y se reemplazaron solo las filas de los PDF reintentados."
                )

                renderizar_resultado_lote_guardado(resultado_combinado)
                lote_ejecutado_en_esta_corrida = True
            else:
                st.warning("No hay PDFs disponibles para reintentar.")

if st.session_state.get("ultimo_lote") and not lote_ejecutado_en_esta_corrida:
    renderizar_resultado_lote_guardado(st.session_state.get("ultimo_lote"))

st.divider()
st.caption("Recomendación: para la primera prueba usa 2 o 3 PDFs antes de correr 30 o 40.")
