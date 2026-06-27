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
import signal
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
TIMEOUTS_PERSISTENTES_PATH = SETTINGS_DIR / "timeouts.json"

# Timeouts defensivos para evitar que un PDF bloquee todo el lote.
# El usuario puede ajustarlos desde la interfaz antes de procesar.
OPENCODE_TIMEOUT_SEGUNDOS_DEFAULT = 900  # 15 minutos por llamada a OpenCode
PDF_TIMEOUT_SEGUNDOS_DEFAULT = 1500      # 25 minutos por PDF activo en el lote

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


def limitar_entero(valor, minimo: int, maximo: int, default: int) -> int:
    """
    Convierte un valor a entero y lo limita a un rango seguro para la UI.
    """
    try:
        numero = int(valor)
    except Exception:
        numero = int(default)

    return max(int(minimo), min(int(maximo), numero))


def cargar_timeouts_persistentes() -> dict:
    """
    Carga la última configuración de timeouts guardada por el usuario.

    Se guarda en minutos porque así se muestra en la interfaz.
    Si el archivo no existe o está corrupto, se usan los defaults defensivos.
    """
    default_opencode_minutos = OPENCODE_TIMEOUT_SEGUNDOS_DEFAULT // 60
    default_pdf_minutos = PDF_TIMEOUT_SEGUNDOS_DEFAULT // 60

    config = {
        "timeout_opencode_minutos": limitar_entero(default_opencode_minutos, 5, 45, 15),
        "timeout_pdf_minutos": limitar_entero(default_pdf_minutos, 10, 90, 25),
    }

    try:
        if not TIMEOUTS_PERSISTENTES_PATH.exists():
            return config

        data = json.loads(TIMEOUTS_PERSISTENTES_PATH.read_text(encoding="utf-8"))

        config["timeout_opencode_minutos"] = limitar_entero(
            data.get("timeout_opencode_minutos"),
            5,
            45,
            config["timeout_opencode_minutos"],
        )
        config["timeout_pdf_minutos"] = limitar_entero(
            data.get("timeout_pdf_minutos"),
            5,
            90,
            config["timeout_pdf_minutos"],
        )
    except Exception:
        return config

    return config


def guardar_timeouts_persistentes(
    timeout_opencode_minutos: int,
    timeout_pdf_minutos: int,
) -> None:
    """
    Guarda automáticamente los timeouts elegidos para reutilizarlos al reiniciar la app.
    """
    try:
        timeout_opencode_minutos = limitar_entero(timeout_opencode_minutos, 5, 45, 15)
        timeout_pdf_minutos = limitar_entero(timeout_pdf_minutos, 5, 90, 25)

        TIMEOUTS_PERSISTENTES_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "timeout_opencode_minutos": timeout_opencode_minutos,
            "timeout_pdf_minutos": timeout_pdf_minutos,
            "timeout_opencode_segundos": timeout_opencode_minutos * 60,
            "timeout_pdf_segundos": timeout_pdf_minutos * 60,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        TIMEOUTS_PERSISTENTES_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
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



def terminar_arbol_proceso(proceso: subprocess.Popen, timeout_gracia: float = 5.0) -> None:
    """
    Intenta terminar el proceso principal y sus hijos.

    Esto es importante para OpenCode porque puede dejar procesos hijos activos.
    En Windows se usa taskkill /T /F; en Linux/Mac se usa el process group.
    """
    if not proceso or proceso.poll() is not None:
        return

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proceso.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(proceso.pid), signal.SIGTERM)
            except Exception:
                proceso.terminate()
    except Exception:
        try:
            proceso.terminate()
        except Exception:
            pass

    try:
        proceso.wait(timeout=timeout_gracia)
    except Exception:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proceso.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                try:
                    os.killpg(os.getpgid(proceso.pid), signal.SIGKILL)
                except Exception:
                    proceso.kill()
        except Exception:
            pass


def ejecutar_opencode(
    prompt: str,
    txt_path: Path,
    modelo_opencode: str = '',
    cwd: Path | None = None,
    timeout_segundos: int = OPENCODE_TIMEOUT_SEGUNDOS_DEFAULT,
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

    timeout_segundos = int(timeout_segundos or OPENCODE_TIMEOUT_SEGUNDOS_DEFAULT)
    inicio = time.time()
    proceso = None

    try:
        popen_kwargs = {
            "cwd": str(workdir),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }

        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        proceso = subprocess.Popen(comando, **popen_kwargs)
        stdout, stderr = proceso.communicate(timeout=timeout_segundos)

        stdout = quitar_ansi(stdout or "")
        stderr = quitar_ansi(stderr or "")

        return {
            "ok": proceso.returncode == 0,
            "returncode": proceso.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "command": comando,
            "cwd": str(workdir),
            "timeout_segundos": timeout_segundos,
            "duracion_segundos": round(time.time() - inicio, 2),
            "timeout": False,
        }

    except subprocess.TimeoutExpired as e:
        stdout = quitar_ansi(e.stdout or "")
        stderr = quitar_ansi(e.stderr or "")
        terminar_arbol_proceso(proceso)

        return {
            "ok": False,
            "error": f"OpenCode tardó más de {formatear_duracion(timeout_segundos)} y se canceló por timeout.",
            "stdout": stdout,
            "stderr": stderr,
            "command": comando,
            "cwd": str(workdir),
            "timeout_segundos": timeout_segundos,
            "duracion_segundos": round(time.time() - inicio, 2),
            "timeout": True,
        }

    except Exception as e:
        terminar_arbol_proceso(proceso)
        return {
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "command": comando,
            "cwd": str(workdir),
            "timeout_segundos": timeout_segundos,
            "duracion_segundos": round(time.time() - inicio, 2),
            "timeout": False,
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
    timeout_opencode_segundos: int = OPENCODE_TIMEOUT_SEGUNDOS_DEFAULT,
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
        "Timeout OpenCode": formatear_duracion(timeout_opencode_segundos),
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
        timeout_segundos=timeout_opencode_segundos,
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


def crear_fila_error_timeout_lote(
    nombre_archivo: str,
    modelo_opencode: str,
    inicio_archivo: float,
    timeout_pdf_segundos: int,
    fase_actual: str,
    detalle: str = "",
) -> dict:
    """
    Crea una fila final cuando el watchdog del lote detecta que un PDF activo
    excedió el tiempo máximo permitido.

    La ejecución interna puede seguir unos minutos en segundo plano, pero el lote
    no queda bloqueado esperando ese PDF. El archivo queda como error reintentable.
    """
    fase = fase_actual or "Timeout del lote"
    error = (
        f"El PDF superó el tiempo máximo activo de {formatear_duracion(timeout_pdf_segundos)}. "
        f"Última fase registrada: {fase}."
    )

    if detalle:
        error += f" Detalle: {detalle}"

    return {
        "Archivo": sanitizar_nombre_archivo(nombre_archivo),
        "Estado": "Error timeout lote",
        "Fase actual": "Timeout del lote",
        "Duración": formatear_duracion(time.time() - inicio_archivo),
        "Worker dir": "Puede seguir activo temporalmente en segundo plano",
        "Nivel": "",
        "Prompt usado": "",
        "Modelo OpenCode": modelo_opencode or "Default OpenCode",
        "Timeout OpenCode": "",
        "Nombre": "",
        "Programa al que aspira": "",
        "Plan": "",
        "Programa origen": "",
        "Créditos homologados": "",
        "TXT LLMWhisperer": "",
        "Respuesta OpenCode": "",
        "Archivo AHK": "No generado",
        "Error": error,
    }


def guardar_artifactos_parciales_lote(run_outputs_dir: Path, filas_por_indice: dict[int, dict]) -> None:
    """
    Guarda resultados parciales para no perder los PDF ya completados si otro PDF
    queda trabado o si la sesión se interrumpe durante un lote grande.
    """
    try:
        filas_parciales = [
            filas_por_indice[index]
            for index in sorted(filas_por_indice)
        ]

        if not filas_parciales:
            return

        parcial_csv_path = run_outputs_dir / "resumen_resultados_parcial.csv"
        guardar_csv_resumen(parcial_csv_path, filas_parciales)

        filas_error = obtener_filas_con_error(filas_parciales)
        errores_parcial_path = run_outputs_dir / "resumen_errores_reintentables_parcial.csv"

        if filas_error:
            guardar_csv_resumen(errores_parcial_path, filas_error)

        crear_zip_ahk(run_outputs_dir, filas_parciales)
    except Exception:
        pass


def ejecutar_lote_streamlit(
    pdf_jobs: list[ArchivoSubidoEnMemoria],
    prompt_pregrado: str,
    prompt_posgrado: str,
    modelo_opencode: str,
    max_workers_opencode: int,
    etiqueta_boton: str = "Procesamiento",
    parent_run_id: str | None = None,
    timeout_pdf_segundos: int = PDF_TIMEOUT_SEGUNDOS_DEFAULT,
    timeout_opencode_segundos: int = OPENCODE_TIMEOUT_SEGUNDOS_DEFAULT,
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
    timeouts_path = run_outputs_dir / "timeouts.txt"
    metadata_path = run_outputs_dir / "metadata_lote.json"

    with open(prompt_pregrado_path, "w", encoding="utf-8") as f:
        f.write(prompt_pregrado)

    with open(prompt_posgrado_path, "w", encoding="utf-8") as f:
        f.write(prompt_posgrado)

    with open(modelo_opencode_path, "w", encoding="utf-8") as f:
        f.write(modelo_opencode or "Default OpenCode")

    with open(concurrencia_path, "w", encoding="utf-8") as f:
        f.write(str(max_workers_opencode))

    with open(timeouts_path, "w", encoding="utf-8") as f:
        f.write(
            f"Timeout PDF activo: {formatear_duracion(timeout_pdf_segundos)}\n"
            f"Timeout OpenCode: {formatear_duracion(timeout_opencode_segundos)}\n"
        )

    # Guardado preventivo de todos los PDFs del lote.
    # Así los PDFs que no alcancen a iniciar por un bloqueo también quedan disponibles para reintento.
    for job in pdf_jobs:
        try:
            pdf_inicial_path = run_uploads_dir / sanitizar_nombre_archivo(job.name)
            if not pdf_inicial_path.exists():
                pdf_inicial_path.write_bytes(job.getbuffer())
        except Exception:
            pass

    guardar_json(metadata_path, {
        "run_id": run_id,
        "tipo_lote": etiqueta_boton,
        "parent_run_id": parent_run_id or "",
        "total_archivos": len(pdf_jobs),
        "modelo_opencode": modelo_opencode or "Default OpenCode",
        "concurrencia": max_workers_opencode,
        "timeout_pdf_segundos": timeout_pdf_segundos,
        "timeout_opencode_segundos": timeout_opencode_segundos,
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
    inicio_real_por_indice = {}
    indices_cerrados = set()

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
            f"**Timeout PDF activo:** {formatear_duracion(timeout_pdf_segundos)}\n"
            f"**Timeout OpenCode:** {formatear_duracion(timeout_opencode_segundos)}\n\n"
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

            if index in indices_cerrados:
                continue

            if index not in inicio_real_por_indice:
                inicio_real_por_indice[index] = evento.get("ts") or time.time()

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
            timeout_opencode_segundos=timeout_opencode_segundos,
        )

    renderizar_estado()

    workers = max(1, min(int(max_workers_opencode or 1), total or 1))

    executor = ThreadPoolExecutor(max_workers=workers)
    futuros = {}
    pendientes = list(enumerate(pdf_jobs, start=1))
    trabajos_enviados = set()

    def enviar_siguiente_job() -> bool:
        if not pendientes:
            return False

        index, job = pendientes.pop(0)
        trabajos_enviados.add(index)
        futuros[executor.submit(ejecutar_job, index, job)] = (index, job.name, time.time())
        return True

    try:
        for _ in range(workers):
            if not enviar_siguiente_job():
                break

        while futuros:
            consumir_eventos_progreso()

            done, _ = wait(
                list(futuros.keys()),
                timeout=0.5,
                return_when=FIRST_COMPLETED,
            )

            jobs_completados_en_iteracion = 0

            for futuro in done:
                index, nombre_archivo, inicio_archivo = futuros.pop(futuro)

                if index in indices_cerrados:
                    continue

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
                        "Timeout OpenCode": formatear_duracion(timeout_opencode_segundos),
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
                indices_cerrados.add(index)
                jobs_completados_en_iteracion += 1

                estado_por_indice[index].update({
                    "Estado": fila.get("Estado", "Finalizado"),
                    "Fase actual": fila.get("Fase actual", "Finalizado"),
                    "Avance PDF": "100%",
                    "Duración": fila.get("Duración", ""),
                    "Detalle": f"Estado final: {fila.get('Estado', 'Desconocido')}",
                    "Archivo AHK": fila.get("Archivo AHK", "No generado"),
                    "Error": fila.get("Error", ""),
                })

                guardar_artifactos_parciales_lote(run_outputs_dir, filas_por_indice)

            # Solo se envían nuevos trabajos cuando un worker terminó realmente.
            # Si un worker se marcó por timeout, no asumimos que el hilo quedó libre.
            for _ in range(jobs_completados_en_iteracion):
                enviar_siguiente_job()

            ahora = time.time()
            futuros_timeout = []

            for futuro, (index, nombre_archivo, inicio_submit) in list(futuros.items()):
                if index in indices_cerrados:
                    futuros_timeout.append((futuro, index, nombre_archivo, inicio_submit))
                    continue

                inicio_real = inicio_real_por_indice.get(index)

                # No se aplica timeout a PDFs que todavía están en cola y no han empezado.
                if not inicio_real:
                    continue

                if ahora - inicio_real >= timeout_pdf_segundos:
                    futuros_timeout.append((futuro, index, nombre_archivo, inicio_real))

            for futuro, index, nombre_archivo, inicio_archivo in futuros_timeout:
                if futuro not in futuros:
                    continue

                futuros.pop(futuro, None)
                indices_cerrados.add(index)

                estado_actual = estado_por_indice.get(index, {})
                fila_timeout = crear_fila_error_timeout_lote(
                    nombre_archivo=nombre_archivo,
                    modelo_opencode=modelo_opencode,
                    inicio_archivo=inicio_archivo,
                    timeout_pdf_segundos=timeout_pdf_segundos,
                    fase_actual=estado_actual.get("Fase actual", ""),
                    detalle=estado_actual.get("Detalle", ""),
                )

                filas_por_indice[index] = fila_timeout

                try:
                    futuro.cancel()
                except Exception:
                    pass

                estado_por_indice[index].update({
                    "Estado": fila_timeout.get("Estado", "Error timeout lote"),
                    "Fase actual": fila_timeout.get("Fase actual", "Timeout del lote"),
                    "Avance PDF": "100%",
                    "Duración": fila_timeout.get("Duración", ""),
                    "Detalle": fila_timeout.get("Error", ""),
                    "Archivo AHK": "No generado",
                    "Error": fila_timeout.get("Error", ""),
                })

                guardar_artifactos_parciales_lote(run_outputs_dir, filas_por_indice)

            renderizar_estado()

        # Si todos los workers activos quedaron bloqueados y aún había PDFs sin iniciar,
        # no los dejamos invisibles. Se marcan como reintentables para que el lote cierre.
        if pendientes:
            for index, job in pendientes:
                fila_no_iniciado = crear_fila_error_timeout_lote(
                    nombre_archivo=job.name,
                    modelo_opencode=modelo_opencode,
                    inicio_archivo=time.time(),
                    timeout_pdf_segundos=timeout_pdf_segundos,
                    fase_actual="No iniciado por bloqueo de workers",
                    detalle=(
                        "No se procesó porque los workers activos quedaron bloqueados o cerrados por timeout. "
                        "Puedes reintentarlo desde la sección de errores."
                    ),
                )
                fila_no_iniciado["Estado"] = "Error no iniciado"
                fila_no_iniciado["Fase actual"] = "No iniciado"

                filas_por_indice[index] = fila_no_iniciado
                indices_cerrados.add(index)

                estado_por_indice[index].update({
                    "Estado": fila_no_iniciado.get("Estado", "Error no iniciado"),
                    "Fase actual": fila_no_iniciado.get("Fase actual", "No iniciado"),
                    "Avance PDF": "100%",
                    "Duración": fila_no_iniciado.get("Duración", ""),
                    "Detalle": fila_no_iniciado.get("Error", ""),
                    "Archivo AHK": "No generado",
                    "Error": fila_no_iniciado.get("Error", ""),
                })

            pendientes.clear()
            guardar_artifactos_parciales_lote(run_outputs_dir, filas_por_indice)
            renderizar_estado()

    finally:
        # No esperamos indefinidamente a threads que puedan haber quedado bloqueados.
        # Los PDFs cerrados por timeout ya quedan en la tabla como reintentables.
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=False)
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
    st.write(f"**Timeouts usados:** `{timeouts_path}`")
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
        "timeouts_path": str(timeouts_path),
        "timeout_pdf_segundos": timeout_pdf_segundos,
        "timeout_opencode_segundos": timeout_opencode_segundos,
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

st.set_page_config(
    page_title="PDF Batch Parser",
    page_icon="📄",
    layout="wide",
)

st.markdown(
    """
    <style>
    .main .block-container {
        padding-top: 1.1rem;
        padding-bottom: 2rem;
        max-width: 1500px;
    }
    h1, h2, h3 {
        letter-spacing: -0.02em;
    }
    .app-shell {
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
    .panel-title {
        font-size: 1.2rem;
        font-weight: 700;
        margin-bottom: 0.25rem;
        color: #0f172a;
    }
    .panel-subtitle {
        color: #64748b;
        font-size: 0.95rem;
        margin-bottom: 0.8rem;
    }
    div[data-testid="stExpander"] details {
        border: 1px solid #dbe4f0;
        border-radius: 14px;
        background: #ffffff;
    }
    div[data-testid="stExpander"] summary {
        font-size: 1rem;
        font-weight: 600;
    }
    div[data-testid="stVerticalBlock"] div[data-testid="stButton"] > button {
        border-radius: 12px;
        font-weight: 700;
    }
    div[data-testid="stDownloadButton"] > button {
        width: 100%;
        border-radius: 12px;
        font-weight: 700;
    }
    .primary-cta-note {
        color: #64748b;
        font-size: 0.92rem;
        margin-top: 0.4rem;
    }
    .mini-note {
        font-size: 0.85rem;
        color: #64748b;
    }
    .retry-alert-card {
        border: 2px solid #f97316;
        background: linear-gradient(135deg, #fff7ed 0%, #fffbeb 100%);
        border-radius: 20px;
        padding: 1.1rem 1.25rem;
        margin-top: 1.15rem;
        margin-bottom: 0.85rem;
        box-shadow: 0 14px 32px rgba(249, 115, 22, 0.14);
    }
    .retry-alert-card h3 {
        color: #9a3412;
        margin: 0 0 0.35rem 0;
        font-size: 1.45rem;
        line-height: 1.15;
    }
    .retry-alert-card p {
        color: #7c2d12;
        margin: 0;
        font-size: 1rem;
    }
    .retry-alert-card strong {
        color: #7c2d12;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def construir_estado_chip(label: str, value: str) -> str:
    return f"""
    <div class=\"status-chip\">
        <span class=\"label\">{label}</span>
        <span class=\"value\">{value}</span>
    </div>
    """


def resumen_para_panel(resultado_lote: dict | None, total_seleccionados: int) -> dict:
    if resultado_lote and (resultado_lote.get("filas") or []):
        filas = resultado_lote.get("filas") or []
        filas_error = resultado_lote.get("filas_error") or obtener_filas_con_error(filas)
        total = len(filas)
        completados = sum(1 for f in filas if f.get("Estado") == "Completado")
        detenidos = sum(
            1
            for f in filas
            if "detenido" in quitar_tildes(str(f.get("Estado", ""))).lower()
        )
        errores = len(filas_error)
        progreso = 100 if total else 0
        procesados = total
        zip_ahk_path = resultado_lote.get("zip_ahk_path", "")
        run_id = resultado_lote.get("run_id", "")
        return {
            "completados": completados,
            "errores": errores,
            "detenidos": detenidos,
            "reintentos": errores,
            "progreso": progreso,
            "procesados": procesados,
            "total": total,
            "zip_ahk_path": zip_ahk_path,
            "run_id": run_id,
            "tiene_resultado": True,
        }

    return {
        "completados": 0,
        "errores": 0,
        "detenidos": 0,
        "reintentos": 0,
        "progreso": 0,
        "procesados": 0,
        "total": total_seleccionados,
        "zip_ahk_path": "",
        "run_id": "",
        "tiene_resultado": False,
    }


api_keys = obtener_api_keys_llmwhisperer()
opencode_path = shutil.which("opencode")
ultimo_lote = st.session_state.get("ultimo_lote")

api_value = f"Conectado ({len(api_keys)} key(s))" if api_keys else "Sin API key"
opencode_value = "Disponible" if opencode_path else "No encontrado"

st.markdown(
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

if "modelos_opencode_resultado" not in st.session_state:
    st.session_state.modelos_opencode_resultado = obtener_modelos_opencode(refresh=False)

if "pdf_uploader_version" not in st.session_state:
    st.session_state["pdf_uploader_version"] = 0

prompt_pregrado = cargar_prompt_persistente(PROMPT_PREGRADO_PATH, PROMPT_PREGRADO)
prompt_posgrado = cargar_prompt_persistente(PROMPT_POSGRADO_PATH, PROMPT_POSGRADO)

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

timeouts_persistidos = cargar_timeouts_persistentes()

with st.container():
    col_left, col_center, col_right = st.columns([1.05, 1.65, 1.0], gap="large")

    with col_left:
        st.markdown('<div class="panel-title">⚡ Configuración rápida</div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-subtitle">Define el modelo, ajusta los prompts y deja guardadas las tolerancias del procesamiento.</div>', unsafe_allow_html=True)

        if st.button("🔄 Actualizar modelos", use_container_width=True, key="btn_actualizar_modelos_rapido"):
            with st.spinner("Consultando modelos con opencode models --refresh..."):
                st.session_state.modelos_opencode_resultado = obtener_modelos_opencode(refresh=True)
                modelos_resultado = st.session_state.modelos_opencode_resultado
                modelos_detectados = modelos_resultado.get("models", [])
                opciones_modelo = [opcion_default_modelo] + modelos_detectados

        modelo_seleccionado_ui = st.selectbox(
            "Modelo OpenCode",
            options=opciones_modelo,
            index=min(indice_modelo_guardado, max(0, len(opciones_modelo) - 1)),
            key="modelo_detectado_opencode",
            help="Selecciona un modelo detectado automáticamente por OpenCode o escribe uno manualmente más abajo.",
        )

        modelo_manual = st.text_input(
            "Modelo manual (opcional)",
            value=modelo_manual_guardado,
            placeholder="Ejemplo: provider/model",
            key="modelo_manual_opencode",
        )

        if modelo_manual.strip():
            modelo_opencode = modelo_manual.strip()
        else:
            modelo_opencode = "" if modelo_seleccionado_ui == opcion_default_modelo else modelo_seleccionado_ui

        if modelo_opencode != modelo_guardado_previo:
            guardar_modelo_opencode_persistente(modelo_opencode)

        if modelo_opencode:
            st.success(f"Modelo activo: {modelo_opencode}")
        else:
            st.info("Se usará el modelo por defecto de OpenCode.")

        with st.expander("📝 Prompt Pregrado", expanded=False):
            prompt_pregrado = st.text_area(
                "Edita el prompt de Pregrado",
                value=prompt_pregrado,
                height=250,
                key="prompt_pregrado",
                label_visibility="collapsed",
            )
            st.caption(f"Ruta: {PROMPT_PREGRADO_PATH}")

        with st.expander("📝 Prompt Posgrado", expanded=False):
            prompt_posgrado = st.text_area(
                "Edita el prompt de Posgrado",
                value=prompt_posgrado,
                height=250,
                key="prompt_posgrado",
                label_visibility="collapsed",
            )
            st.caption(f"Ruta: {PROMPT_POSGRADO_PATH}")

        if st.button("💾 Guardar prompts", use_container_width=True, key="btn_guardar_prompts_redisenado"):
            guardar_prompt_persistente(PROMPT_PREGRADO_PATH, prompt_pregrado)
            guardar_prompt_persistente(PROMPT_POSGRADO_PATH, prompt_posgrado)
            st.success("Prompts guardados correctamente.")

        st.markdown("#### Tolerancia a bloqueos y timeouts")
        col_timeout_1, col_timeout_2 = st.columns(2)

        with col_timeout_1:
            timeout_opencode_minutos = st.number_input(
                "OpenCode (min)",
                min_value=5,
                max_value=45,
                value=int(timeouts_persistidos["timeout_opencode_minutos"]),
                step=5,
                key="timeout_opencode_minutos",
                help="Si OpenCode supera este tiempo en un PDF, se cancela esa llamada y el PDF queda como error reintentable.",
            )

        with col_timeout_2:
            timeout_pdf_minutos = st.number_input(
                "PDF activo (min)",
                min_value=5,
                max_value=90,
                value=int(timeouts_persistidos["timeout_pdf_minutos"]),
                step=5,
                key="timeout_pdf_minutos",
                help="Protección externa del lote: si un PDF activo supera este tiempo, se marca como timeout para que el lote pueda cerrar. Puedes bajarlo hasta 5 minutos.",
            )

        timeout_opencode_segundos = int(timeout_opencode_minutos) * 60
        timeout_pdf_segundos = int(timeout_pdf_minutos) * 60

        if (
            int(timeout_opencode_minutos) != int(timeouts_persistidos["timeout_opencode_minutos"])
            or int(timeout_pdf_minutos) != int(timeouts_persistidos["timeout_pdf_minutos"])
            or not TIMEOUTS_PERSISTENTES_PATH.exists()
        ):
            guardar_timeouts_persistentes(
                timeout_opencode_minutos=int(timeout_opencode_minutos),
                timeout_pdf_minutos=int(timeout_pdf_minutos),
            )

        max_workers_limite_ui = 1
        st.markdown("#### PDFs en paralelo")
        st.caption("Recomendado: 2 a 6 procesos simultáneos. Máximo permitido: 12 para equipos/proveedores estables.")

        # Este slider se ajustará realmente después de seleccionar archivos, pero se muestra desde ya.
        max_workers_opencode = st.slider(
            "Procesos simultáneos",
            min_value=1,
            max_value=12,
            value=3,
            step=1,
            key="max_workers_opencode_ui_base",
        )

        if max_workers_opencode > 6:
            st.warning(
                "Modo de alta concurrencia activo. Más de 6 procesos simultáneos puede aumentar errores por límites de API, saturación de OpenCode o timeouts. "
                "Úsalo gradualmente y valida primero con una tanda pequeña."
            )

        st.info(
            "Si un PDF se queda colgado, la app lo marcará como error reintentable y seguirá construyendo el resumen y el ZIP con los AHK que sí se generaron."
        )
        st.caption(
            f"Configuración persistente: {TIMEOUTS_PERSISTENTES_PATH} · OpenCode: {timeout_opencode_minutos} min ({timeout_opencode_segundos} s) · PDF activo: {timeout_pdf_minutos} min ({timeout_pdf_segundos} s)"
        )

        if not modelos_resultado.get("ok"):
            with st.expander("Ver error al listar modelos OpenCode", expanded=False):
                st.text_area(
                    "Salida de opencode models",
                    value=modelos_resultado.get("error", "") or modelos_resultado.get("raw", ""),
                    height=180,
                )

    with col_center:
        st.markdown('<div class="panel-title">📂 Carga de PDFs</div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-subtitle">Carga los archivos, revisa la tanda y dispara el procesamiento completo desde esta zona central.</div>', unsafe_allow_html=True)

        col_upload_title, col_upload_action = st.columns([3, 1])
        with col_upload_title:
            st.caption("Arrastra y suelta tus PDFs o selecciónalos manualmente.")
        with col_upload_action:
            if st.button(
                "🧹 Reemplazar tanda",
                help="Limpia los PDFs cargados actualmente para seleccionar una nueva tanda.",
                key="boton_reemplazar_tanda_pdfs",
                use_container_width=True,
            ):
                st.session_state["pdf_uploader_version"] += 1
                reiniciar_app_streamlit()

        uploaded_files = st.file_uploader(
            "Selecciona uno o varios archivos PDF",
            type=["pdf"],
            accept_multiple_files=True,
            key=f"pdf_uploader_{st.session_state['pdf_uploader_version']}",
            label_visibility="collapsed",
        )

        if uploaded_files:
            max_workers_limite_ui = min(12, len(uploaded_files))
            max_workers_opencode = max(1, min(int(max_workers_opencode), max_workers_limite_ui))
            if max_workers_limite_ui == 1:
                max_workers_opencode = 1
            st.success(f"📚 {len(uploaded_files)} PDF(s) listos para procesar")
        else:
            max_workers_limite_ui = 1
            st.info("Todavía no hay PDFs cargados.")

        if uploaded_files:
            archivos_rows = [
                {
                    "Archivo": file.name,
                    "Tamaño (KB)": round(len(file.getvalue()) / 1024, 1),
                }
                for file in uploaded_files
            ]
            with st.expander(f"Vista previa del lote · {len(archivos_rows)} archivo(s)", expanded=True):
                st.dataframe(archivos_rows, use_container_width=True, hide_index=True, height=min(310, 36 * (len(archivos_rows) + 1)))
        else:
            with st.expander("Vista previa del lote", expanded=False):
                st.caption("Aquí aparecerán los PDFs cargados para revisión rápida.")

        requisitos_faltantes = []
        if not uploaded_files:
            requisitos_faltantes.append("cargar al menos un PDF")
        if not prompt_pregrado.strip():
            requisitos_faltantes.append("definir el prompt de Pregrado")
        if not prompt_posgrado.strip():
            requisitos_faltantes.append("definir el prompt de Posgrado")
        if not api_keys:
            requisitos_faltantes.append("configurar API keys de LLMWhisperer")
        if not opencode_path:
            requisitos_faltantes.append("tener OpenCode disponible en el PATH")

        disabled = len(requisitos_faltantes) > 0
        procesar_click = st.button(
            "▶ Iniciar procesamiento",
            disabled=disabled,
            use_container_width=True,
            type="primary",
            key="btn_iniciar_procesamiento_principal",
        )

        if disabled:
            st.warning("Antes de iniciar, falta: " + ", ".join(requisitos_faltantes) + ".")
        else:
            st.markdown('<div class="primary-cta-note">El procesamiento es seguro y todos los archivos se manejan localmente dentro del lote actual.</div>', unsafe_allow_html=True)

    with col_right:
        st.markdown('<div class="panel-title">📊 Resumen del lote</div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-subtitle">Métricas rápidas del último resultado disponible o de la tanda actual seleccionada.</div>', unsafe_allow_html=True)

        total_seleccionados = len(uploaded_files) if uploaded_files else 0
        resumen = resumen_para_panel(ultimo_lote, total_seleccionados)

        metric_row_1_col_1, metric_row_1_col_2 = st.columns(2)
        metric_row_2_col_1, metric_row_2_col_2 = st.columns(2)

        metric_row_1_col_1.metric("Completados", resumen["completados"])
        metric_row_1_col_2.metric("Errores", resumen["errores"])
        metric_row_2_col_1.metric("Detenidos", resumen["detenidos"])
        metric_row_2_col_2.metric("Reintentos", resumen["reintentos"])

        st.markdown("**Progreso general**")
        st.progress(int(resumen["progreso"]))
        st.caption(f"{resumen['procesados']} de {resumen['total']} PDFs procesados")

        if resumen["run_id"]:
            st.caption(f"Último lote disponible: `{resumen['run_id']}`")

        zip_ahk_path_panel = resumen.get("zip_ahk_path") or ""
        if zip_ahk_path_panel:
            path_zip_panel = Path(zip_ahk_path_panel)
            if path_zip_panel.exists() and path_zip_panel.is_file():
                with open(path_zip_panel, "rb") as f:
                    st.download_button(
                        label="⬇️ Descargar ZIP AHK",
                        data=f,
                        file_name="scripts_ahk.zip",
                        mime="application/zip",
                        use_container_width=True,
                        key=f"descarga_zip_panel_{resumen['run_id'] or 'sin_run'}",
                    )
            else:
                st.caption("El ZIP AHK del último lote ya no está disponible en disco.")
        else:
            st.button("⬇️ Descargar ZIP AHK", disabled=True, use_container_width=True, key="zip_ahk_deshabilitado_panel")
            st.caption("El ZIP se habilitará cuando exista un lote con AHK generados.")

        filas_error_panel = (ultimo_lote or {}).get("filas_error", []) if ultimo_lote else []
        if filas_error_panel:
            st.warning(f"Hay {len(filas_error_panel)} archivo(s) con error reintentable.")
            max_workers_retry_limite = min(max(1, max_workers_opencode), len(filas_error_panel)) if filas_error_panel else 1
            max_workers_retry_limite = max(1, max_workers_retry_limite)

            if max_workers_retry_limite <= 1:
                concurrencia_reintento = 1
                st.caption("Reintento con 1 proceso simultáneo porque solo hay 1 PDF con error.")
            else:
                concurrencia_reintento = st.slider(
                    "Paralelo en reintento",
                    min_value=1,
                    max_value=max_workers_retry_limite,
                    value=max_workers_retry_limite,
                    step=1,
                    key=f"concurrencia_reintento_panel_{(ultimo_lote or {}).get('run_id','sin_run')}",
                )

            reintentar_click = st.button(
                f"🔁 Reintentar {len(filas_error_panel)} PDF(s) con error",
                disabled=not api_keys or not opencode_path,
                use_container_width=True,
                key=f"boton_reintentar_panel_{(ultimo_lote or {}).get('run_id','sin_run')}",
            )
        else:
            concurrencia_reintento = 1
            reintentar_click = False
            if ultimo_lote:
                st.success("No hay errores reintentables en el último lote.")
            else:
                st.info("Después de tu primer procesamiento, aquí verás el resumen consolidado y los reintentos.")

        with st.expander("Actividad y rutas del lote", expanded=False):
            if ultimo_lote:
                st.write(f"**Run ID:** `{ultimo_lote.get('run_id', '')}`")
                st.write(f"**Carpeta de salida:** `{ultimo_lote.get('run_outputs_dir', '')}`")
                st.write(f"**CSV resultados:** `{ultimo_lote.get('resumen_csv_path', '')}`")
                if ultimo_lote.get("errores_csv_path"):
                    st.write(f"**CSV errores:** `{ultimo_lote.get('errores_csv_path', '')}`")
            else:
                st.caption("Aún no hay actividad registrada en esta sesión.")

# Sección destacada de reintento: queda visible fuera del panel lateral para que el usuario
# no tenga que buscarla dentro del resumen ni dentro del detalle del último procesamiento.
filas_error_destacadas = (st.session_state.get("ultimo_lote") or {}).get("filas_error", [])

if filas_error_destacadas:
    run_id_reintento_destacado = (st.session_state.get("ultimo_lote") or {}).get("run_id", "sin_run")
    st.markdown(
        f"""
        <div class="retry-alert-card">
            <h3>🔁 Archivos con error listos para reintentar</h3>
            <p>
                Hay <strong>{len(filas_error_destacadas)}</strong> PDF(s) con error reintentable en el lote
                <strong>{run_id_reintento_destacado}</strong>. Puedes reintentar solo esos archivos sin perder
                los AHK que ya se generaron correctamente.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    columnas_error_visibles = [
        columna
        for columna in ["Archivo", "Estado", "Fase actual", "Duración", "Error"]
        if filas_error_destacadas and columna in filas_error_destacadas[0]
    ]

    with st.expander("Ver PDFs que se van a reintentar", expanded=True):
        if columnas_error_visibles:
            st.dataframe(
                [
                    {columna: fila.get(columna, "") for columna in columnas_error_visibles}
                    for fila in filas_error_destacadas
                ],
                use_container_width=True,
                hide_index=True,
                height=min(300, 40 * (len(filas_error_destacadas) + 1)),
            )
        else:
            st.dataframe(filas_error_destacadas, use_container_width=True)

    col_retry_info, col_retry_action = st.columns([1, 2], gap="large")

    with col_retry_info:
        max_workers_retry_destacado = min(max(1, int(max_workers_opencode)), len(filas_error_destacadas))
        max_workers_retry_destacado = max(1, max_workers_retry_destacado)

        if max_workers_retry_destacado <= 1:
            concurrencia_reintento_destacada = 1
            st.info("Reintento configurado con 1 proceso simultáneo porque solo hay 1 PDF con error.")
        else:
            concurrencia_reintento_destacada = st.slider(
                "Procesos simultáneos para este reintento",
                min_value=1,
                max_value=max_workers_retry_destacado,
                value=max_workers_retry_destacado,
                step=1,
                key=f"concurrencia_reintento_destacada_{run_id_reintento_destacado}",
            )

        st.caption(
            "El reintento solo procesará los PDFs con error. Los resultados correctos anteriores se conservarán."
        )

    with col_retry_action:
        reintentar_click_destacado = st.button(
            f"🔁 Reintentar ahora {len(filas_error_destacadas)} PDF(s) con error",
            disabled=not api_keys or not opencode_path,
            use_container_width=True,
            type="primary",
            key=f"boton_reintentar_destacado_{run_id_reintento_destacado}",
        )
        st.caption(
            "Después del reintento, la tabla final quedará combinada: PDFs correctos anteriores + PDFs reintentados actualizados."
        )

    if reintentar_click_destacado:
        concurrencia_reintento = concurrencia_reintento_destacada
        reintentar_click = True

lote_ejecutado_en_esta_corrida = False

if procesar_click:
    pdf_jobs = [
        ArchivoSubidoEnMemoria(file.name, file.getvalue())
        for file in (uploaded_files or [])
    ]

    ejecutar_lote_streamlit(
        pdf_jobs=pdf_jobs,
        prompt_pregrado=prompt_pregrado,
        prompt_posgrado=prompt_posgrado,
        modelo_opencode=modelo_opencode,
        max_workers_opencode=max_workers_opencode,
        etiqueta_boton="Procesamiento por lote",
        timeout_pdf_segundos=timeout_pdf_segundos,
        timeout_opencode_segundos=timeout_opencode_segundos,
    )
    lote_ejecutado_en_esta_corrida = True
    ultimo_lote = st.session_state.get("ultimo_lote")

if 'reintentar_click' in locals() and reintentar_click:
    ultimo_lote = st.session_state.get("ultimo_lote")
    filas_error = (ultimo_lote or {}).get("filas_error", [])
    run_id_anterior = (ultimo_lote or {}).get("run_id", "")

    if filas_error:
        pdf_jobs_retry, no_encontrados = cargar_pdf_jobs_desde_lote(run_id_anterior, filas_error)

        if no_encontrados:
            st.error(
                "No se pudieron encontrar estos PDFs originales para reintentar: "
                + ", ".join(no_encontrados)
            )

        if pdf_jobs_retry:
            resultado_base_antes_reintento = dict(ultimo_lote)

            resultado_reintento = ejecutar_lote_streamlit(
                pdf_jobs=pdf_jobs_retry,
                prompt_pregrado=prompt_pregrado,
                prompt_posgrado=prompt_posgrado,
                modelo_opencode=modelo_opencode,
                max_workers_opencode=concurrencia_reintento,
                etiqueta_boton="Reintento de errores",
                parent_run_id=run_id_anterior,
                timeout_pdf_segundos=timeout_pdf_segundos,
                timeout_opencode_segundos=timeout_opencode_segundos,
            )

            resultado_combinado = reconstruir_resultado_lote_combinado(
                resultado_base=resultado_base_antes_reintento,
                resultado_reintento=resultado_reintento,
            )

            st.session_state["ultimo_lote"] = resultado_combinado
            ultimo_lote = resultado_combinado

            st.success(
                "✅ Resultado combinado actualizado: se conservaron los AHK y las filas correctas del primer intento, y se reemplazaron solo las filas de los PDF reintentados."
            )

            with st.expander("Ver resultado combinado después del reintento", expanded=True):
                renderizar_resultado_lote_guardado(resultado_combinado)
            lote_ejecutado_en_esta_corrida = True
        else:
            st.warning("No hay PDFs disponibles para reintentar.")

if st.session_state.get("ultimo_lote") and not lote_ejecutado_en_esta_corrida:
    st.divider()
    with st.expander("Ver detalle del último procesamiento", expanded=False):
        renderizar_resultado_lote_guardado(st.session_state.get("ultimo_lote"))

st.divider()
st.caption(
    "Consejo: para una primera prueba, usa 2 o 3 PDFs en paralelo. Si todo funciona bien, luego aumenta gradualmente a 4 o más según la capacidad de tu equipo y la estabilidad de OpenCode."
)
