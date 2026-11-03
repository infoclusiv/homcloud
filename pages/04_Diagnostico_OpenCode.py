"""Diagnóstico seguro de la fase OpenCode de lotes locales.

No presenta contenidos originales ni logs potencialmente personales: solamente
estados, duraciones, tamaños y códigos de error detectados.
"""
from pathlib import Path
import streamlit as st

from diagnostico_opencode import resumir_lote
from recuperacion_lotes import listar_lotes

BASE_DIR = Path(__file__).resolve().parents[1]
st.set_page_config(page_title="Diagnóstico OpenCode", layout="wide")
st.title("🔎 Diagnóstico OpenCode")
st.caption(
    "Comprueba qué está haciendo OpenCode mientras los PDFs están en curso. "
    "Esta página se puede abrir en otra pestaña sin interrumpir el procesamiento."
)
st.warning(
    "No compartas los archivos opencode_stdout.log ni opencode_stderr.log: "
    "pueden contener información personal o mensajes de proveedores."
)

if st.button("🔄 Actualizar diagnóstico", key="actualizar_diagnostico_opencode", type="primary"):
    st.rerun()

lotes = listar_lotes(BASE_DIR)
if not lotes:
    st.info("No hay lotes locales disponibles.")
    st.stop()

run_id = st.selectbox("Lote que deseas investigar", lotes)
filas = resumir_lote(BASE_DIR, run_id)

if not filas:
    st.info(
        "Este lote no contiene registros de diagnóstico. "
        "Los lotes creados antes de instalar esta mejora solo tienen los mensajes "
        "de OpenCode que el proveedor pudo conservar en sus logs generales."
    )
    st.code(
        "opencode --version\n"
        "opencode debug paths\n"
        "python -m diagnostico_opencode probar "
        "--model opencode/deepseek-v4.1-flash-free --timeout 45",
        language="bash",
    )
    st.stop()

terminados = sum(f.get("Estado OpenCode") == "completado" for f in filas)
errores = sum(f.get("Estado OpenCode") in ("error", "error_ejecucion") for f in filas)
activos = sum(f.get("Estado OpenCode") in ("en_ejecucion", "iniciando", "cancelando") for f in filas)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Workers con diagnóstico", len(filas))
col2.metric("OpenCode en curso", activos)
col3.metric("Finalizados", terminados)
col4.metric("Con error", errores)

st.dataframe(
    filas,
    hide_index=True,
    use_container_width=True,
    column_order=[
        "Worker", "Modelo", "Estado OpenCode", "Causa detectada",
        "Terminación", "Segundos", "Sin salida (s)",
        "Salida (bytes)", "Errores (bytes)", "Código salida",
    ],
)
st.caption(
    "Sin mensajes en stderr no significa que el modelo funcione bien: "
    "también puede estar esperando respuesta remota, reintentando o generando "
    "texto sin terminar. Las métricas muestran qué se observó, no adivinan la causa."
)

st.markdown("#### Cómo interpretar los diagnósticos")
st.markdown(
    "Un **HTTP 429** indica un posible límite de cuota o velocidad. "
    "Un **HTTP 5xx** apunta a un error del servicio. "
    "Si la salida permanece en **0 bytes**, no hay respuesta visible todavía. "
    "Si crece sin terminar, puede existir un bucle de generación. "
    "La terminación **cancelado_por_timeout_del_lote** significa que "
    "homcloud detuvo el subproceso tras agotar el tiempo total del PDF."
)
