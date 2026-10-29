"""Historial acumulado de homologaciones: consulta y descarga CSV.

Los resultados están en Firestore para ambos Cloud Shell; no hay PDFs en esta
colección, solo campos estructurados de cada procesamiento.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from pathlib import Path

from historial_homologaciones import (
    COLUMNAS,
    csv_historial_bytes,
    exportar_historial,
    importar_lotes_existentes,
)
from programas_planes_sync import ErrorSincronizacion, proyecto_configurado

BASE_DIR = Path(__file__).resolve().parents[1]
st.set_page_config(page_title="Historial de homologaciones", layout="wide")
st.title("📋 Historial de homologaciones")
st.caption(
    "Aquí se guardan los datos de las homologaciones de todas las tandas, "
    "sin conservar PDFs antiguos. Puedes descargar un CSV acumulado para "
    "hacer análisis de programas, planes y créditos."
)

try:
    proyecto = proyecto_configurado()
except ErrorSincronizacion as exc:
    st.error(f"Configuración Firestore: {exc}")
    st.stop()

st.info(
    f"Fuente: Firestore compartido ({proyecto})" if proyecto
    else "Fuente: CSV local de este Cloud Shell (Firestore no configurado)."
)
st.caption(
    "El historial registra cada intento con su identificador de lote y estado. "
    "Los reintentos pueden generar un registro adicional para el mismo documento. "
    "No contiene PDFs, AHK ni respuestas completas de OpenCode."
)

with st.expander("Importar resultados de sesiones existentes", expanded=False):
    st.caption(
        "Si tienes lotes antiguos que todavía están en disco, impórtalos al "
        "historial antes de que se eliminen. Esta operación no borra documentos."
    )
    if st.button("📥 Importar lotes disponibles", key="importar_historiales"):
        with st.spinner("Archivando CSV antiguos sin borrar originales..."):
            resultado = importar_lotes_existentes(BASE_DIR)
        st.success(f"{resultado['archivados']} lote(s) revisados y archivados.")
        if resultado["omitidos_activos"]:
            st.info(f"{resultado['omitidos_activos']} lote(s) en ejecución se omitieron.")
        if resultado["errores"]:
            st.warning(
                f"{len(resultado['errores'])} lote(s) no se archivaron. "
                "Sus archivos se conservarán."
            )
            with st.expander("Detalles de lotes no archivados"):
                st.text("\n".join(resultado["errores"][:20]))

if st.button("🔄 Consultar historial completo", type="primary", key="consultar_historial"):
    try:
        with st.spinner("Leyendo el historial guardado..."):
            filas = exportar_historial(BASE_DIR)
            st.session_state["filas_historial_homcloud"] = filas
    except (OSError, ErrorSincronizacion) as exc:
        st.error(
            f"No se pudo recuperar el historial: {exc}. "
            "No se reemplazó la consulta anterior."
        )

filas = st.session_state.get("filas_historial_homcloud")
if filas is None:
    st.caption("Pulsa Consultar historial completo para ver registros y preparar el CSV.")
    st.stop()
if not filas:
    st.info("Todavía no hay homologaciones archivadas.")
    st.stop()

tabla = pd.DataFrame(filas)
for col in COLUMNAS:
    if col not in tabla.columns:
        tabla[col] = ""
tabla = tabla[list(COLUMNAS)]
col_total, col_ok, col_lotes = st.columns(3)
col_total.metric("Registros", len(tabla))
col_ok.metric("Completados", (tabla["Estado"] == "Completado").sum())
col_lotes.metric("Lotes", tabla["Lote"].nunique())

col_buscar, col_estado = st.columns([2, 1])
with col_buscar:
    busqueda = st.text_input(
        "Buscar programa, PDF o persona",
        placeholder="Ej.: MAESTRÍA EN EDUCACIÓN, DERECHO...",
    )
with col_estado:
    opciones_estados = ["Todos"] + sorted(
        str(v) for v in tabla["Estado"].dropna().unique() if str(v)
    )
    estado = st.selectbox("Estado", opciones_estados)

filtrada = tabla
if busqueda.strip():
    termino = busqueda.strip()
    campos = ["Archivo", "Programa origen", "Programa al que aspira", "Plan"]
    mascara = pd.Series(False, index=tabla.index)
    for campo in campos:
        mascara |= tabla[campo].astype(str).str.contains(
            termino, regex=False, case=False, na=False
        )
    filtrada = filtrada.loc[mascara]
if estado != "Todos":
    filtrada = filtrada.loc[filtrada["Estado"] == estado]

columnas_prioritarias = [
    "Fecha", "Archivo", "Programa origen", "Programa al que aspira",
    "Plan", "Créditos homologados", "Estado", "Lote",
]
st.dataframe(
    filtrada,
    column_order=columnas_prioritarias + [c for c in COLUMNAS if c not in columnas_prioritarias],
    use_container_width=True,
    hide_index=True,
    height=440,
)
st.caption(f"{len(filtrada)} registro(s) visibles de {len(tabla)} almacenados.")

col_todo, col_filtrado = st.columns(2)
with col_todo:
    st.download_button(
        "⬇️ Descargar historial completo CSV",
        data=csv_historial_bytes(tabla.to_dict("records")),
        file_name="historial_homologaciones_completo.csv",
        mime="text/csv",
        use_container_width=True,
        key="exportar_historial_todo",
    )
with col_filtrado:
    st.download_button(
        "⬇️ Descargar resultados filtrados CSV",
        data=csv_historial_bytes(filtrada.to_dict("records")),
        file_name="historial_homologaciones_filtrado.csv",
        mime="text/csv",
        use_container_width=True,
        key="exportar_historial_filtrado",
    )
