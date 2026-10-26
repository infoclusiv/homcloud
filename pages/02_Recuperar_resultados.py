"""Descargas y recuperación independientes del procesamiento principal."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from recuperacion_lotes import (
    csv_recuperado_bytes,
    listar_lotes,
    recuperar_lote,
    zip_recuperado_bytes,
)

BASE_DIR = Path(__file__).resolve().parents[1]
st.set_page_config(page_title="Recuperar resultados", layout="wide")
st.title("📦 Recuperar resultados de procesamiento")
st.caption(
    "Abre esta página en otra pestaña mientras se procesan los PDFs. "
    "Pulsa Actualizar para ver nuevos documentos terminados. "
    "Los resultados se leen del disco de ESTE Cloud Shell."
)
st.warning(
    "No cierres la pestaña que está procesando archivos y mantén Web Preview "
    "restringido a usuarios autorizados: los resultados pueden contener datos personales."
)

if st.button("🔄 Actualizar lotes y resultados", type="primary"):
    st.rerun()

lotes = listar_lotes(BASE_DIR)
if not lotes:
    st.info("Todavía no hay lotes guardados localmente.")
    st.stop()

run_id = st.selectbox("Lote a recuperar (los más recientes primero)", lotes)
try:
    resultado = recuperar_lote(BASE_DIR, run_id)
except (OSError, ValueError, UnicodeError) as exc:
    st.error(f"No se pudo recuperar este lote: {exc}")
    st.stop()

filas = resultado["filas"]
completados = sum(1 for f in filas if str(f.get("Estado", "")).casefold() == "completado")
pendientes = sum(1 for f in filas if f.get("Estado") == "Error no iniciado")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Resultados encontrados", len(filas))
col2.metric("Completados", completados)
col3.metric("Errores por reintentar", len(resultado["filas_error"]))
col4.metric("Pendientes recuperados", pendientes)
st.caption(
    "Un resultado parcial no significa que el procesamiento haya terminado. "
    "Los PDFs sin fila guardada aparecen como errores reintentables."
)
if resultado["es_resultado_combinado"]:
    st.info("Se han integrado los resultados del lote anterior y los reintentos disponibles.")

if filas:
    st.dataframe(filas[:300], use_container_width=True, hide_index=True)
    if len(filas) > 300:
        st.caption("La vista muestra 300 filas como máximo; el CSV descargado incluye todas.")

    csv_bytes = csv_recuperado_bytes(filas)
    zip_bytes, num_ahk = zip_recuperado_bytes(filas, BASE_DIR)
    col_csv, col_zip = st.columns(2)
    with col_csv:
        st.download_button(
            "⬇️ Descargar CSV recuperado",
            data=csv_bytes,
            file_name=f"{run_id}_resultados_recuperados.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with col_zip:
        if num_ahk:
            st.download_button(
                f"⬇️ Descargar {num_ahk} AHK recuperados (ZIP)",
                data=zip_bytes,
                file_name=f"{run_id}_scripts_recuperados.zip",
                mime="application/zip",
                use_container_width=True,
            )
        else:
            st.info("No hay scripts AHK completados para este lote.")
else:
    st.info("Este lote no tiene resultados disponibles todavía.")

st.caption(
    "Para reintentar desde la app principal, usa «Recuperar resultados parciales» "
    "cuando no tengas un lote activo en esa sesión; conserva siempre los PDFs originales."
)
