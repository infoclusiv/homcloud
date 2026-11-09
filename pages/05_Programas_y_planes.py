"""Edición dedicada al catálogo programa → plan, sin espacio vacío en Inicio."""
from pathlib import Path
import streamlit as st

from programas_planes import CAMPO_PERMITIR_PLAN_VACIO
from programas_planes_sync import (
    ErrorSincronizacion, leer_configuracion, guardar_configuracion,
)

ROOT = Path(__file__).resolve().parents[1]
RUTA = ROOT / "settings" / "programas_planes.json"
st.set_page_config(page_title="Programas y planes · homcloud", layout="wide")
st.title("🎓 Programas y planes")
st.caption("Edita y sincroniza el catálogo. El procesamiento diario se mantiene en Inicio.")
st.page_link("app.py", label="← Volver al procesador")

try:
    programas, revision, proyecto = leer_configuracion(RUTA)
except ErrorSincronizacion as exc:
    st.error(f"No fue posible leer el catálogo: {exc}")
    st.stop()

if "_revision_editor_planes" not in st.session_state:
    st.session_state["_revision_editor_planes"] = revision

col1, col2 = st.columns([2, 1])
with col1:
    st.metric("Programas registrados", len(programas))
with col2:
    st.caption(f"☁️ Firestore compartido: {proyecto}" if proyecto else "📁 Configuración local")

if st.button("🔄 Recargar programas desde la nube", key="recargar_planes_pagina"):
    st.session_state.pop("editor_programas_planes", None)
    st.session_state["_revision_editor_planes"] = revision
    st.rerun()

if st.session_state["_revision_editor_planes"] != revision:
    st.warning(
        "El catálogo cambió en otra sesión. Recarga antes de guardar; "
        "no se sobrescribirán ediciones remotas."
    )

st.caption(
    "Puedes añadir filas. Los alias se separan con punto y coma. "
    "P2, Plan 2 y 2 se comparan de forma equivalente."
)
editados = st.data_editor(
    programas or [{
        "Programa al que aspira": "", "Plan": "", "Alias": "",
        CAMPO_PERMITIR_PLAN_VACIO: False,
    }],
    num_rows="dynamic",
    hide_index=True,
    use_container_width=True,
    key="editor_programas_planes",
    height=550,
    column_config={
        "Programa al que aspira": st.column_config.TextColumn(
            "Programa oficial", width="large",
        ),
        "Plan": st.column_config.TextColumn("Plan esperado", width="small"),
        "Alias": st.column_config.TextColumn(
            "Alias y abreviaciones", width="large",
        ),
        CAMPO_PERMITIR_PLAN_VACIO: st.column_config.CheckboxColumn(
            "Plan vacío válido",
            help="Si está marcado, un plan vacío también puede ser correcto.",
        ),
    },
)

if st.button(
    "💾 Guardar programas y planes",
    key="guardar_planes_pagina",
    type="primary",
    disabled=st.session_state["_revision_editor_planes"] != revision,
):
    try:
        guardados = guardar_configuracion(
            editados, RUTA,
            revision_esperada=st.session_state["_revision_editor_planes"],
        )
    except (ValueError, ErrorSincronizacion) as exc:
        st.error(f"No se guardaron cambios: {exc}")
    else:
        st.success(f"Se guardaron {len(guardados)} programas.")
        st.session_state.pop("editor_programas_planes", None)
        st.session_state.pop("_revision_editor_planes", None)
        st.rerun()
