from pathlib import Path

import pandas as pd
import streamlit as st

from programas_planes import (
    CAMPO_PERMITIR_PLAN_VACIO,
    cargar_programas_planes,
    construir_mapa_programas_planes,
    evaluar_plan,
    guardar_programas_planes,
)


_APP_CORE_PATH = Path(__file__).with_name("app_core.py")
_APP_SOURCE = _APP_CORE_PATH.read_text(encoding="utf-8")
PROGRAMAS_PLANES_PATH = Path(__file__).with_name("settings") / "programas_planes.json"

COLOR_PLAN_CORRECTO = "rgb(0, 204, 47)"
COLOR_PLAN_INCORRECTO = "rgb(255, 124, 28)"


def estilizar_tabla_planes(filas, configuracion):
    dataframe = pd.DataFrame(filas)
    if dataframe.empty or "Plan" not in dataframe.columns:
        return dataframe

    mapa_programas_planes = construir_mapa_programas_planes(configuracion)

    def aplicar_estilo(fila):
        estilos = pd.Series("", index=fila.index)
        estado = evaluar_plan(
            fila.get("Programa al que aspira", ""),
            fila.get("Plan", ""),
            mapa_programas_planes,
        )

        if estado == "correcto":
            estilos["Plan"] = (
                f"background-color: {COLOR_PLAN_CORRECTO}; "
                "color: white; font-weight: 700;"
            )
        elif estado in {"incorrecto", "sin_configuracion"}:
            estilos["Plan"] = (
                f"background-color: {COLOR_PLAN_INCORRECTO}; "
                "color: white; font-weight: 700;"
            )

        return estilos

    return dataframe.style.apply(aplicar_estilo, axis=1)


def resumir_validacion_planes(filas, configuracion) -> dict[str, int]:
    mapa_programas_planes = construir_mapa_programas_planes(configuracion)
    conteo = {
        "correctos": 0,
        "incorrectos": 0,
        "sin_configuracion": 0,
        "sin_datos": 0,
    }

    for fila in filas or []:
        estado = evaluar_plan(
            fila.get("Programa al que aspira", ""),
            fila.get("Plan", ""),
            mapa_programas_planes,
        )
        clave_conteo = {
            "correcto": "correctos",
            "incorrecto": "incorrectos",
            "sin_configuracion": "sin_configuracion",
            "sin_datos": "sin_datos",
        }[estado]
        conteo[clave_conteo] += 1

    return conteo


def renderizar_tabla_resumen_planes(filas) -> None:
    configuracion = cargar_programas_planes(PROGRAMAS_PLANES_PATH)
    conteo = resumir_validacion_planes(filas, configuracion)
    requieren_revision = conteo["incorrectos"] + conteo["sin_configuracion"]

    st.caption(
        f"🟢 {conteo['correctos']} plan(es) coinciden · "
        f"🟠 {requieren_revision} requieren revisión. "
        "El naranja indica un plan diferente o un programa aún no configurado."
    )
    st.dataframe(
        estilizar_tabla_planes(filas, configuracion),
        use_container_width=True,
        hide_index=True,
    )


_OLD_COMPLETION_BLOCK = '''    lote_ejecutado_en_esta_corrida = True
    ultimo_lote = st.session_state.get("ultimo_lote")

if 'reintentar_click' in locals() and reintentar_click:
'''

_NEW_COMPLETION_BLOCK = '''    lote_ejecutado_en_esta_corrida = True
    ultimo_lote = st.session_state.get("ultimo_lote")

    # El panel de reintento se construye antes de ejecutar el lote. Al finalizar,
    # session_state ya contiene los errores, pero la interfaz necesita un nuevo
    # ciclo de Streamlit para mostrarlos sin depender de un clic de descarga.
    reiniciar_app_streamlit()

if 'reintentar_click' in locals() and reintentar_click:
'''

if _OLD_COMPLETION_BLOCK not in _APP_SOURCE:
    raise RuntimeError(
        "No se encontró el bloque esperado para activar el reintento inmediato."
    )

_APP_SOURCE = _APP_SOURCE.replace(
    _OLD_COMPLETION_BLOCK,
    _NEW_COMPLETION_BLOCK,
    1,
)

_OLD_COLUMN_ORDER_BLOCK = '''def guardar_csv_resumen(path: Path, filas: list):
    if not filas:
        return

    fieldnames = list(filas[0].keys())

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filas)
'''

_NEW_COLUMN_ORDER_BLOCK = '''COLUMNAS_RESULTADO_ORDEN = (
    "Archivo",
    "Nivel",
    "Prompt usado",
    "Programa origen",
    "Programa al que aspira",
    "Plan",
    "Créditos homologados",
    "Duración",
    "Estado",
    "Fase actual",
    "Worker dir",
    "Modelo OpenCode",
    "Timeout OpenCode",
    "Nombre",
    "TXT LLMWhisperer",
    "Respuesta OpenCode",
    "Archivo AHK",
    "Error",
)


def ordenar_columnas_resultado(filas: list) -> list:
    if not filas:
        return filas

    columnas_presentes = []
    for fila in filas:
        for columna in fila.keys():
            if columna not in columnas_presentes:
                columnas_presentes.append(columna)

    orden = [
        columna
        for columna in COLUMNAS_RESULTADO_ORDEN
        if columna in columnas_presentes
    ]
    orden.extend(
        columna
        for columna in columnas_presentes
        if columna not in orden
    )

    return [
        {columna: fila.get(columna, "") for columna in orden}
        for fila in filas
    ]


def guardar_csv_resumen(path: Path, filas: list):
    if not filas:
        return

    filas_ordenadas = ordenar_columnas_resultado(filas)
    fieldnames = list(filas_ordenadas[0].keys())

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filas_ordenadas)
'''

if _OLD_COLUMN_ORDER_BLOCK not in _APP_SOURCE:
    raise RuntimeError(
        "No se encontró el bloque esperado para configurar el orden de columnas."
    )

_APP_SOURCE = _APP_SOURCE.replace(
    _OLD_COLUMN_ORDER_BLOCK,
    _NEW_COLUMN_ORDER_BLOCK,
    1,
)

_OLD_OPERATIONAL_CONFIG_MARKER = '''timeouts_persistidos = cargar_timeouts_persistentes()

with st.container():
'''

_NEW_OPERATIONAL_CONFIG_BLOCK = '''timeouts_persistidos = cargar_timeouts_persistentes()
programas_planes_guardados = cargar_programas_planes(PROGRAMAS_PLANES_PATH)

with st.container():
    st.markdown(
        '<div class="panel-title">⚙️ Configuración operativa</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="panel-subtitle">La concurrencia y la relación programa–plan quedan accesibles arriba, antes de cargar los PDFs.</div>',
        unsafe_allow_html=True,
    )

    col_parallel, col_programas = st.columns([1.0, 2.15], gap="large")

    with col_parallel:
        max_workers_limite_ui = 1
        max_workers_opencode = st.slider(
            "Procesos simultáneos",
            min_value=1,
            max_value=12,
            value=3,
            step=1,
            key="max_workers_opencode_ui_base",
            help="Recomendado: entre 2 y 6. El valor se limita automáticamente al número de PDFs cargados.",
        )
        if max_workers_opencode > 6:
            st.warning("Más de 6 procesos puede aumentar errores de API, saturación o timeouts.")
        else:
            st.caption("Recomendado: 2 a 6 procesos simultáneos.")

    with col_programas:
        with st.expander(
            f"🎓 Configurar programa → plan ({len(programas_planes_guardados)} guardados)",
            expanded=False,
        ):
            st.caption(
                "El catálogo inicial ya está cargado. Separa varios alias con punto y coma; "
                "cada alias se reconocerá como el mismo programa oficial."
            )
            programas_planes_editados = st.data_editor(
                programas_planes_guardados
                or [{
                    "Programa al que aspira": "",
                    "Plan": "",
                    "Alias": "",
                    CAMPO_PERMITIR_PLAN_VACIO: False,
                }],
                num_rows="dynamic",
                hide_index=True,
                use_container_width=True,
                key="editor_programas_planes",
                column_config={
                    "Programa al que aspira": st.column_config.TextColumn(
                        "Programa oficial",
                        width="large",
                    ),
                    "Plan": st.column_config.TextColumn(
                        "Plan esperado",
                        width="small",
                        help="P2, Plan 2 y 2 se consideran equivalentes.",
                    ),
                    "Alias": st.column_config.TextColumn(
                        "Alias y abreviaciones",
                        width="large",
                        help="Separa cada variante con punto y coma.",
                    ),
                    CAMPO_PERMITIR_PLAN_VACIO: st.column_config.CheckboxColumn(
                        "Plan vacío válido",
                        help=(
                            "Cuando está activo, el programa aparece verde si el Plan "
                            "está vacío o si coincide con el plan esperado."
                        ),
                    ),
                },
            )

            col_guardar_programas, col_ruta_programas = st.columns([1.0, 1.6])
            with col_guardar_programas:
                guardar_programas_click = st.button(
                    "💾 Guardar programas y planes",
                    use_container_width=True,
                    key="btn_guardar_programas_planes",
                )
            with col_ruta_programas:
                st.caption(f"Configuración persistente: {PROGRAMAS_PLANES_PATH}")

            if guardar_programas_click:
                try:
                    programas_guardados = guardar_programas_planes(
                        programas_planes_editados,
                        PROGRAMAS_PLANES_PATH,
                    )
                except ValueError as error_programas:
                    st.error(str(error_programas))
                else:
                    st.success(
                        f"Se guardaron {len(programas_guardados)} relación(es) programa–plan."
                    )
                    reiniciar_app_streamlit()

            st.caption(
                "La comparación ignora mayúsculas, tildes, puntuación y espacios. "
                "También reconoce los alias, equipara P2, Plan 2 y 2, y permite "
                "Plan vacío únicamente en las filas marcadas."
            )

with st.container():
'''

if _APP_SOURCE.count(_OLD_OPERATIONAL_CONFIG_MARKER) != 1:
    raise RuntimeError(
        "No se encontró el punto esperado para insertar la configuración operativa."
    )

_APP_SOURCE = _APP_SOURCE.replace(
    _OLD_OPERATIONAL_CONFIG_MARKER,
    _NEW_OPERATIONAL_CONFIG_BLOCK,
    1,
)

_OLD_PARALLEL_CONFIG_BLOCK = '''        max_workers_limite_ui = 1
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
'''

_NEW_PARALLEL_CONFIG_BLOCK = '''        st.info(
            "La concurrencia ahora se configura en la sección operativa superior. "
            "Si un PDF se bloquea, quedará como error reintentable sin detener el resumen final."
        )
        st.caption(
            f"Timeouts persistentes: {TIMEOUTS_PERSISTENTES_PATH} · OpenCode: {timeout_opencode_minutos} min · PDF activo: {timeout_pdf_minutos} min"
        )
'''

if _APP_SOURCE.count(_OLD_PARALLEL_CONFIG_BLOCK) != 1:
    raise RuntimeError(
        "No se encontró el bloque anterior de procesos simultáneos para reubicarlo."
    )

_APP_SOURCE = _APP_SOURCE.replace(
    _OLD_PARALLEL_CONFIG_BLOCK,
    _NEW_PARALLEL_CONFIG_BLOCK,
    1,
)

_OLD_RESULTS_TABLE_LINE = "    st.dataframe(filas, use_container_width=True)"
_NEW_RESULTS_TABLE_LINE = (
    "    renderizar_tabla_resumen_planes("
    "ordenar_columnas_resultado(filas))"
)

if _APP_SOURCE.count(_OLD_RESULTS_TABLE_LINE) != 2:
    raise RuntimeError(
        "No se encontraron las dos tablas de resumen esperadas."
    )

_APP_SOURCE = _APP_SOURCE.replace(
    _OLD_RESULTS_TABLE_LINE,
    _NEW_RESULTS_TABLE_LINE,
)

_OLD_ERROR_TABLE_LINE = "        st.dataframe(filas_error, use_container_width=True)"
_NEW_ERROR_TABLE_LINE = (
    "        st.dataframe("
    "ordenar_columnas_resultado(filas_error), "
    "use_container_width=True)"
)

if _APP_SOURCE.count(_OLD_ERROR_TABLE_LINE) != 2:
    raise RuntimeError(
        "No se encontraron las dos tablas de errores esperadas."
    )

_APP_SOURCE = _APP_SOURCE.replace(
    _OLD_ERROR_TABLE_LINE,
    _NEW_ERROR_TABLE_LINE,
)

exec(compile(_APP_SOURCE, str(_APP_CORE_PATH), "exec"), globals(), globals())
