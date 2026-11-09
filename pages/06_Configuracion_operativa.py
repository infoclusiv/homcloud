"""Configuración operativa y almacenamiento: fuera del procesador principal."""
from pathlib import Path
import streamlit as st

from configuracion_global import leer_preferencias, guardar_preferencias
from programas_planes_sync import ErrorSincronizacion
from retencion_local import inventario, candidatos_limpieza, limpiar_archivos_antiguos

BASE = Path(__file__).resolve().parents[1]
st.set_page_config(page_title="Configuración operativa · homcloud", layout="wide")
st.title("⚙️ Configuración operativa")
st.caption("Predeterminados globales, retención y gestión del espacio.")
st.page_link("app.py", label="← Volver al procesador")

try:
    preferencias, revision, proyecto = leer_preferencias()
except (ErrorSincronizacion, ValueError) as exc:
    st.error(f"No se pudo cargar la configuración compartida: {exc}")
    st.stop()

if "_revision_preferencias_operativas" not in st.session_state:
    st.session_state["_revision_preferencias_operativas"] = revision
desactualizado = st.session_state["_revision_preferencias_operativas"] != revision

with st.container(border=True):
    st.subheader("Predeterminados")
    st.caption(f"☁️ Firestore: {proyecto}" if proyecto else "📁 Configuración local")
    if desactualizado:
        st.warning("Otro Cloud Shell modificó estas preferencias. Recarga antes de guardar.")
    c1, c2, c3 = st.columns(3)
    with c1:
        procesos = st.number_input(
            "Procesos simultáneos predeterminados", min_value=1, max_value=20,
            value=int(preferencias["procesos_predeterminados"]), step=1,
            key="procesos_globales_pagina",
        )
    with c2:
        retencion = st.number_input(
            "Limpieza manual (días)", min_value=1, max_value=90,
            value=int(preferencias["retencion_dias"]), step=1,
            key="retencion_manual_pagina",
        )
    with c3:
        automatico = st.number_input(
            "Eliminar PDFs antiguos (días)", min_value=1, max_value=90,
            value=int(preferencias.get("retencion_pdfs_dias", 3)), step=1,
            key="retencion_automatica_pagina",
            help="Solo después de archivar filas del lote. Se verifica al utilizar homcloud.",
        )
    c_save, c_reload = st.columns([1, 1])
    with c_save:
        guardar = st.button(
            "💾 Guardar predeterminado global",
            type="primary", disabled=desactualizado,
            use_container_width=True,
        )
    with c_reload:
        if st.button("🔄 Recargar desde Firestore", use_container_width=True):
            st.session_state["_revision_preferencias_operativas"] = revision
            for key in ("procesos_globales_pagina", "retencion_manual_pagina",
                        "retencion_automatica_pagina", "max_workers_opencode_ui_base"):
                st.session_state.pop(key, None)
            st.rerun()
    if guardar:
        try:
            guardar_preferencias({
                "procesos_predeterminados": int(procesos),
                "retencion_dias": int(retencion),
                "retencion_pdfs_dias": int(automatico),
            }, revision)
        except (ValueError, ErrorSincronizacion) as exc:
            st.error(f"No se pudo guardar: {exc}")
        else:
            st.session_state.pop("_revision_preferencias_operativas", None)
            st.session_state.pop("max_workers_opencode_ui_base", None)
            st.success("Preferencias guardadas.")
            st.rerun()

with st.expander("🧹 Almacenamiento local y limpieza manual", expanded=False):
    st.caption(
        "El análisis se ejecuta solo al solicitarlo. El historial CSV/Firestore "
        "no se elimina. Los lotes activos quedan protegidos."
    )
    ultimo = st.session_state.get("ultimo_lote") or {}
    protegidos = {
        str(ultimo.get("run_id") or ""),
        str(ultimo.get("parent_run_id") or ""),
    }
    dias = int(preferencias["retencion_dias"])
    if st.button("🔎 Analizar almacenamiento"):
        st.session_state["_uso_almacenamiento"] = inventario(BASE)
        st.session_state["_candidatos_almacenamiento"] = candidatos_limpieza(
            BASE, dias, protegidos,
        )
        st.session_state["_retencion_analizada_dias"] = dias
    uso = st.session_state.get("_uso_almacenamiento")
    candidatos = st.session_state.get("_candidatos_almacenamiento") or []
    if uso:
        st.metric("Espacio físico de lotes (estimado)", f"{uso['bytes']/1048576:.1f} MB")
        st.caption(f"{uso['archivos']} archivos · {len(candidatos)} elementos antiguos.")
        for nombre, valores in uso["carpetas"].items():
            st.caption(
                f"{nombre}: {valores['bytes']/1048576:.1f} MB "
                f"({valores['archivos']} archivos)"
            )
        confirmar = st.checkbox(
            "Confirmo que tengo respaldo de los archivos antiguos a eliminar.",
            key="confirmar_limpieza_lotes",
        )
        if st.button(
            "Eliminar archivos antiguos",
            disabled=not confirmar or not candidatos
                     or dias != st.session_state.get("_retencion_analizada_dias"),
        ):
            try:
                borrados = limpiar_archivos_antiguos(BASE, dias, protegidos)
            except (OSError, ValueError, ErrorSincronizacion) as exc:
                st.error(f"No se pudo limpiar: {exc}")
            else:
                st.success(f"Se eliminaron {len(borrados)} elementos antiguos.")
                st.session_state.pop("_uso_almacenamiento", None)
                st.session_state.pop("_candidatos_almacenamiento", None)
    else:
        st.info("Pulsa Analizar almacenamiento para consultar el uso.")
