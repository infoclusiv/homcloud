"""Panel independiente para descargar resultados sin esperar el final del lote.

Abre esta página en otra pestaña de Web Preview mientras procesas. Streamlit
sirve los archivos mediante widgets de descarga, sin copiarlos a /static/.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).resolve().parents[1]
RUNS_DIR = BASE_DIR / "outputs" / "runs"
UPLOADS_DIR = BASE_DIR / "uploads"

st.set_page_config(page_title="Recuperación de lotes", layout="wide")
st.title("📦 Recuperar resultados de procesamiento")
st.caption(
    "Esta página funciona en una pestaña independiente del procesamiento. "
    "Puedes actualizarla y descargar los documentos terminados aunque otro PDF siga ejecutándose. "
    "Los archivos permanecen en el Cloud Shell donde se procesaron."
)
st.warning(
    "Si estás procesando en otra pestaña, no cierres ni reinicies esa pestaña. "
    "No publiques los resultados ni el Web Preview en Internet."
)

RUNS_DIR.mkdir(parents=True, exist_ok=True)


def cargar_filas(csv_path: Path, limite: int = 300) -> list[dict]:
    """Vista limitada para evitar bloquear la interfaz con CSV grandes."""
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as archivo:
            lector = csv.DictReader(archivo)
            filas = []
            for _, fila in zip(range(limite), lector):
                filas.append(fila)
            return filas
    except (OSError, csv.Error, UnicodeError) as exc:
        st.error(f"No se pudo leer la vista previa: {exc}")
        return []


def listar_lotes() -> list[Path]:
    try:
        lotes = [
            p for p in RUNS_DIR.iterdir()
            if p.is_dir() and not p.is_symlink()
            and ((p / "resumen_resultados_parcial.csv").is_file()
                 or (p / "resumen_resultados.csv").is_file())
        ]
        return sorted(lotes, key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []


if st.button("🔄 Actualizar archivos disponibles", use_container_width=False):
    st.rerun()

lotes = listar_lotes()
if not lotes:
    st.info("Todavía no hay CSV parciales o finales disponibles en este Cloud Shell.")
    st.stop()

nombres = [p.name for p in lotes]
opcion = st.selectbox(
    "Selecciona un lote (el más reciente aparece primero)",
    options=nombres,
    index=0,
    key="lote_recuperacion",
)
seleccionado = lotes[nombres.index(opcion)]
csv_final = seleccionado / "resumen_resultados.csv"
csv_parcial = seleccionado / "resumen_resultados_parcial.csv"
csv_actual = csv_final if csv_final.is_file() else csv_parcial
zip_path = seleccionado / "scripts_ahk.zip"
csv_error_final = seleccionado / "resumen_errores_reintentables.csv"
csv_error_parcial = seleccionado / "resumen_errores_reintentables_parcial.csv"
csv_error = csv_error_final if csv_error_final.is_file() else csv_error_parcial

st.subheader(f"Lote {seleccionado.name}")
st.write("**Estado:** " + ("Resultado final disponible" if csv_final.is_file() else "Recuperación parcial"))
try:
    fecha = datetime.fromtimestamp(csv_actual.stat().st_mtime).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    st.caption(f"Último CSV guardado: {fecha}")
except OSError:
    pass

filas = cargar_filas(csv_actual)
completados = sum(1 for fila in filas if fila.get("Estado") == "Completado")
st.metric("Filas disponibles en la vista previa", len(filas))
st.caption(
    f"{completados} completados dentro de la vista previa. "
    "La descarga CSV contiene el archivo completo, no solo las filas visibles."
)
if filas:
    st.dataframe(filas, use_container_width=True, hide_index=True)

col_csv, col_zip, col_error = st.columns(3)
with col_csv:
    if csv_actual.is_file():
        with csv_actual.open("rb") as archivo:
            st.download_button(
                "⬇️ Descargar CSV disponible",
                data=archivo,
                file_name=f"{seleccionado.name}_resultados.csv",
                mime="text/csv",
                use_container_width=True,
            )
with col_zip:
    if zip_path.is_file():
        with zip_path.open("rb") as archivo:
            st.download_button(
                "⬇️ Descargar ZIP AHK disponibles",
                data=archivo,
                file_name=f"{seleccionado.name}_scripts_ahk.zip",
                mime="application/zip",
                use_container_width=True,
            )
    else:
        st.info("Sin scripts AHK terminados.")
with col_error:
    if csv_error.is_file():
        with csv_error.open("rb") as archivo:
            st.download_button(
                "⬇️ Descargar CSV de errores",
                data=archivo,
                file_name=f"{seleccionado.name}_errores.csv",
                mime="text/csv",
                use_container_width=True,
            )
    else:
        st.caption("No existe CSV de errores para este lote.")

st.caption(
    "Si el archivo todavía se está escribiendo, pulsa Actualizar después de "
    "que termine otro PDF. El CSV y ZIP se actualizan progresivamente."
)
