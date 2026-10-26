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
from programas_planes_sync import (
    EdicionDesactualizada,
    ErrorSincronizacion,
    guardar_configuracion,
    leer_configuracion,
    proyecto_configurado,
)
from excel_runtime_patch import aplicar_soporte_excel
from configuracion_global import leer_preferencias, guardar_preferencias
from retencion_local import inventario, candidatos_limpieza, limpiar_archivos_antiguos


BASE_DIR = Path(__file__).resolve().parent
_APP_CORE_PATH = Path(__file__).with_name("app_core.py")
_APP_SOURCE = _APP_CORE_PATH.read_text(encoding="utf-8")
PROGRAMAS_PLANES_PATH = Path(__file__).with_name("settings") / "programas_planes.json"
UPLOADS_DIR_APP = BASE_DIR / "uploads"

COLOR_PLAN_CORRECTO = "rgb(0, 204, 47)"
COLOR_PLAN_INCORRECTO = "rgb(255, 124, 28)"


def _resolver_pdf_original(nombre_archivo: str) -> Path | None:
    """Localiza la copia original del PDF guardada en uploads/<run_id>/.

    Primero intenta las rutas del último lote guardado y después recorre los
    lotes existentes del más reciente al más antiguo. Este fallback también
    permite crear enlaces en el primer render del resumen, antes de que
    `ultimo_lote` haya sido escrito en session_state.
    """
    nombre = Path(str(nombre_archivo or "")).name.strip()
    if not nombre:
        return None

    ultimo_lote = st.session_state.get("ultimo_lote") or {}
    directorios_candidatos = []

    run_uploads_dir = ultimo_lote.get("run_uploads_dir")
    if run_uploads_dir:
        directorios_candidatos.append(Path(run_uploads_dir))

    for clave_run in ("run_id", "parent_run_id"):
        run_id = str(ultimo_lote.get(clave_run) or "").strip()
        if run_id:
            directorios_candidatos.append(UPLOADS_DIR_APP / run_id)

    vistos = set()
    for directorio in directorios_candidatos:
        clave = str(directorio)
        if clave in vistos:
            continue
        vistos.add(clave)
        candidato = directorio / nombre
        if candidato.exists() and candidato.is_file():
            return candidato

    if not UPLOADS_DIR_APP.exists():
        return None

    coincidencias = []
    try:
        for run_dir in UPLOADS_DIR_APP.iterdir():
            if not run_dir.is_dir():
                continue
            candidato = run_dir / nombre
            if candidato.exists() and candidato.is_file():
                try:
                    orden = candidato.stat().st_mtime_ns
                except OSError:
                    orden = 0
                coincidencias.append((orden, candidato))
    except OSError:
        return None

    if not coincidencias:
        return None

    coincidencias.sort(key=lambda item: item[0], reverse=True)
    return coincidencias[0][1]


def preparar_dataframe_con_links_pdf(filas):
    """Conserva los nombres de PDFs sin publicarlos como archivos estáticos.

    La descarga del original se gestiona con controles Streamlit; las tablas
    pueden conservar sus estilos de validación de planes.
    """
    dataframe = pd.DataFrame(filas).copy()
    return dataframe, {}


def mostrar_descarga_pdf_original(filas, sufijo: str) -> None:
    """Descarga bajo la sesión Streamlit: evita copias en static/pdfs."""
    nombres = list(dict.fromkeys(
        str(fila.get("Archivo") or "").strip()
        for fila in (filas or [])
        if str(fila.get("Archivo") or "").strip()
    ))
    disponibles = [(nombre, _resolver_pdf_original(nombre)) for nombre in nombres]
    disponibles = [(nombre, ruta) for nombre, ruta in disponibles if ruta]
    if not disponibles:
        st.caption("Los PDFs originales ya no están disponibles en este Cloud Shell.")
        return
    st.caption("Para proteger los documentos, los PDFs originales ya no se exponen mediante enlaces estáticos.")
    elegido = st.selectbox(
        "PDF original para descargar",
        options=[nombre for nombre, _ in disponibles],
        key=f"elegir_pdf_original_{sufijo}",
    )
    ruta = dict(disponibles)[elegido]
    try:
        with ruta.open("rb") as f:
            st.download_button(
                "⬇️ Descargar PDF original seleccionado",
                data=f,
                file_name=ruta.name,
                mime="application/pdf",
                key=f"descargar_pdf_original_{sufijo}",
            )
    except OSError as exc:
        st.warning(f"No se pudo abrir el PDF original: {exc}")


def estilizar_tabla_planes(filas, configuracion):
    dataframe = filas.copy() if isinstance(filas, pd.DataFrame) else pd.DataFrame(filas)
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
    try:
        configuracion, _, _ = leer_configuracion(PROGRAMAS_PLANES_PATH)
    except ErrorSincronizacion as exc:
        st.error(f"Sincronización de planes no disponible: {exc}")
        st.stop()
    conteo = resumir_validacion_planes(filas, configuracion)
    requieren_revision = conteo["incorrectos"] + conteo["sin_configuracion"]
    dataframe, column_config = preparar_dataframe_con_links_pdf(filas)

    st.caption(
        f"🟢 {conteo['correctos']} plan(es) coinciden · "
        f"🟠 {requieren_revision} requieren revisión. "
        "El naranja indica un plan diferente o un programa aún no configurado."
    )
    st.dataframe(
        estilizar_tabla_planes(dataframe, configuracion),
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
    )
    mostrar_descarga_pdf_original(filas, "resumen")


def renderizar_tabla_errores_con_links(filas) -> None:
    dataframe, column_config = preparar_dataframe_con_links_pdf(filas)
    st.dataframe(
        dataframe,
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
    )
    mostrar_descarga_pdf_original(filas, "errores")


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

    # Escritura atómica: los lectores solo ven un CSV íntegro.
    temporal = path.with_name(path.name + ".tmp")
    try:
        with open(temporal, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(filas_ordenadas)
        os.replace(temporal, path)
    finally:
        temporal.unlink(missing_ok=True)
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
try:
    preferencias_operativas, revision_operativa, proyecto_operativo = leer_preferencias()
    error_operativa = None
except (ErrorSincronizacion, ValueError) as exc:
    preferencias_operativas, revision_operativa, proyecto_operativo = {"procesos_predeterminados": 4}, None, None
    error_operativa = str(exc)
try:
    programas_planes_guardados, revision_planes, proyecto_planes = leer_configuracion(PROGRAMAS_PLANES_PATH)
    error_sync_planes = None
except ErrorSincronizacion as exc:
    programas_planes_guardados, revision_planes, proyecto_planes = [], None, None
    error_sync_planes = str(exc)

if st.session_state.get("_revision_editor_planes") != revision_planes:
    # No sobrescribir silenciosamente la edición ya abierta: el usuario
    # debe pulsar "Recargar de nube" si su revisión difiere.
    if "_revision_editor_planes" not in st.session_state:
        st.session_state["_revision_editor_planes"] = revision_planes

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
        if "_revision_preferencias_operativas" not in st.session_state:
            st.session_state["_revision_preferencias_operativas"] = revision_operativa
        if "max_workers_opencode_ui_base" not in st.session_state:
            st.session_state["max_workers_opencode_ui_base"] = int(preferencias_operativas["procesos_predeterminados"])
        max_workers_opencode = st.slider(
            "Procesos simultáneos",
            min_value=1,
            max_value=20,
            step=1,
            key="max_workers_opencode_ui_base",
            help="La selección actual es para este lote; puedes guardarla como predeterminada para ambas instancias.",
            disabled=bool(error_operativa),
        )
        if error_operativa:
            st.error(f"Preferencias compartidas no disponibles: {error_operativa}")
        else:
            st.caption(f"Predeterminado: {preferencias_operativas['procesos_predeterminados']} · {'Firestore compartido' if proyecto_operativo else 'Modo local'}")
            if st.session_state["_revision_preferencias_operativas"] != revision_operativa:
                st.warning("Las preferencias cambiaron en otra sesión. Recarga antes de guardar.")
            retencion_dias = st.number_input(
                "Retención de archivos (días)", min_value=1, max_value=90,
                value=int(preferencias_operativas["retencion_dias"]), step=1,
                help="Se comparte el número de días; la eliminación se realiza manualmente en cada Cloud Shell.",
                key="retencion_dias_global",
            )
            if st.button("💾 Guardar predeterminado global", key="guardar_concurrencia_global",
                         disabled=st.session_state["_revision_preferencias_operativas"] != revision_operativa):
                try:
                    guardar_preferencias({"procesos_predeterminados": max_workers_opencode, "retencion_dias": int(retencion_dias)}, revision_operativa)
                except (ValueError, ErrorSincronizacion) as exc:
                    st.error(str(exc))
                else:
                    st.session_state.pop("_revision_preferencias_operativas", None)
                    st.success("Valor predeterminado compartido guardado.")
                    reiniciar_app_streamlit()
            if st.button("🔄 Recargar predeterminado", key="recargar_concurrencia_global"):
                st.session_state["max_workers_opencode_ui_base"] = int(preferencias_operativas["procesos_predeterminados"])
                st.session_state["_revision_preferencias_operativas"] = revision_operativa
                reiniciar_app_streamlit()
        if max_workers_opencode > 12:
            st.warning(
                "Alta concurrencia activa (13–20 procesos). Puede aumentar de forma importante "
                "los límites de API, el consumo de CPU/RAM y los timeouts de OpenCode."
            )
        elif max_workers_opencode > 6:
            st.warning("Más de 6 procesos puede aumentar errores de API, saturación o timeouts.")
        else:
            st.caption("Recomendado: 2 a 6 procesos simultáneos. Máximo disponible: 20.")

        with st.expander("🧹 Almacenamiento local", expanded=False):
            uso = inventario(BASE_DIR)
            st.metric("Almacenamiento de lotes", f"{uso['bytes'] / 1048576:.1f} MB")
            st.caption(f"{uso['archivos']} archivos almacenados")
            for nombre_carpeta, datos_carpeta in uso["carpetas"].items():
                st.caption(f"{nombre_carpeta}: {datos_carpeta['bytes'] / 1048576:.1f} MB")
            dias = int(preferencias_operativas.get("retencion_dias", 7))
            lote_activo = st.session_state.get("ultimo_lote") or {}
            protegidos = {str(lote_activo.get("run_id") or ""), str(lote_activo.get("parent_run_id") or "")}
            candidatos = candidatos_limpieza(BASE_DIR, dias, protegidos)
            st.caption(f"Retención: {dias} días · {len(candidatos)} elementos candidatos.")
            confirmar_limpieza = st.checkbox(
                "Ya tengo respaldo de los resultados antiguos", key="confirmar_limpieza_lotes"
            )
            if st.button("Eliminar archivos antiguos", key="borrar_lotes_antiguos",
                         disabled=not confirmar_limpieza or not candidatos):
                try:
                    borrados = limpiar_archivos_antiguos(BASE_DIR, dias, protegidos)
                    st.success(f"Se eliminaron {len(borrados)} elementos antiguos de este Cloud Shell.")
                except OSError as exc:
                    st.error(f"No se pudo completar la limpieza: {exc}")
            st.caption("Limpieza manual local. No afecta al otro Cloud Shell ni a Firestore.")

    with col_programas:
        with st.expander(
            f"🎓 Configurar programa → plan ({len(programas_planes_guardados)} guardados)",
            expanded=False,
        ):
            st.caption(
                "El catálogo inicial ya está cargado. Separa varios alias con punto y coma; "
                "cada alias se reconocerá como el mismo programa oficial."
            )
            if error_sync_planes:
                st.error(f"Configuración remota no disponible: {error_sync_planes}")
                st.warning("No se permiten guardados mientras falla Firestore.")
            elif proyecto_planes:
                st.caption(f"☁️ Configuración central: {proyecto_planes}")
            else:
                st.caption("📁 Modo local (Firestore no configurado).")

            if st.button("🔄 Recargar programas desde la nube", key="btn_recargar_planes", disabled=bool(error_sync_planes)):
                st.session_state.pop("editor_programas_planes", None)
                st.session_state["_revision_editor_planes"] = revision_planes
                reiniciar_app_streamlit()

            if st.session_state.get("_revision_editor_planes") != revision_planes:
                st.warning("Hay cambios guardados desde otra sesión. Recarga antes de guardar.")

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
                    disabled=bool(error_sync_planes) or st.session_state.get("_revision_editor_planes") != revision_planes,
                )
            with col_ruta_programas:
                st.caption(f"Configuración persistente: {PROGRAMAS_PLANES_PATH}")

            if guardar_programas_click:
                try:
                    programas_guardados = guardar_configuracion(
                        programas_planes_editados,
                        PROGRAMAS_PLANES_PATH,
                        revision_esperada=st.session_state.get("_revision_editor_planes"),
                    )
                except (ValueError, ErrorSincronizacion) as error_programas:
                    st.error(str(error_programas))
                else:
                    st.success(
                        f"Se guardaron {len(programas_guardados)} relación(es) programa–plan."
                    )
                    st.session_state.pop("editor_programas_planes", None)
                    st.session_state.pop("_revision_editor_planes", None)
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

# app_core limita otra vez la concurrencia al número de archivos cargados.
# Elevamos también ese límite interno de 12 a 20 para que el valor del slider
# llegue realmente al ThreadPoolExecutor y no quede recortado silenciosamente.
_OLD_CONCURRENCY_LIMIT_LINE = "            max_workers_limite_ui = min(12, len(uploaded_files))"
_NEW_CONCURRENCY_LIMIT_LINE = "            max_workers_limite_ui = min(20, len(uploaded_files))"

if _APP_SOURCE.count(_OLD_CONCURRENCY_LIMIT_LINE) != 1:
    raise RuntimeError(
        "No se encontró el límite interno esperado de 12 procesos simultáneos."
    )

_APP_SOURCE = _APP_SOURCE.replace(
    _OLD_CONCURRENCY_LIMIT_LINE,
    _NEW_CONCURRENCY_LIMIT_LINE,
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
    "        renderizar_tabla_errores_con_links("
    "ordenar_columnas_resultado(filas_error))"
)

if _APP_SOURCE.count(_OLD_ERROR_TABLE_LINE) != 2:
    raise RuntimeError(
        "No se encontraron las dos tablas de errores esperadas."
    )

_APP_SOURCE = _APP_SOURCE.replace(
    _OLD_ERROR_TABLE_LINE,
    _NEW_ERROR_TABLE_LINE,
)

_APP_SOURCE = _APP_SOURCE.replace(
    'with st.expander("Ver detalle del último procesamiento", expanded=False):',
    'with st.expander("Ver detalle del último procesamiento", expanded=True):',
)
_APP_SOURCE = aplicar_soporte_excel(_APP_SOURCE)

exec(compile(_APP_SOURCE, str(_APP_CORE_PATH), "exec"), globals(), globals())