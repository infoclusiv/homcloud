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
from historial_homologaciones import mantenimiento_periodico
from retencion_local import inventario, candidatos_limpieza, limpiar_archivos_antiguos
from pdf_enlaces import publicar_pdf
from configuracion_tabla import (
    ORDEN_PREDETERMINADO,
    leer_orden,
    guardar_orden,
    mover_columna,
    ordenar_visibles,
)


BASE_DIR = Path(__file__).resolve().parent
_APP_CORE_PATH = Path(__file__).with_name("app_core.py")
_APP_SOURCE = _APP_CORE_PATH.read_text(encoding="utf-8")
PROGRAMAS_PLANES_PATH = Path(__file__).with_name("settings") / "programas_planes.json"
UPLOADS_DIR_APP = BASE_DIR / "uploads"

COLOR_PLAN_CORRECTO = "rgb(0, 204, 47)"
COLOR_PLAN_INCORRECTO = "rgb(255, 124, 28)"


def _resolver_pdf_original(nombre_archivo: str) -> Path | None:
    """Busca el PDF solo en el lote actual y en sus lotes anteriores.

    Nunca revisa lotes ajenos por nombre: archivos de distintas personas
    podrían compartir exactamente el mismo nombre.
    """
    from recuperacion_lotes import leer_json, validar_run_id

    nombre = Path(str(nombre_archivo or "")).name.strip()
    if not nombre or nombre in {".", ".."}:
        return None
    ultimo = st.session_state.get("ultimo_lote") or {}
    ids = [
        st.session_state.get("_run_actual_id"),
        ultimo.get("run_id"),
        ultimo.get("parent_run_id"),
    ]
    vistos = set()
    while ids and len(vistos) < 12:
        run_id = str(ids.pop(0) or "")
        if not run_id or run_id in vistos:
            continue
        try:
            validar_run_id(run_id)
        except ValueError:
            continue
        vistos.add(run_id)
        candidato = UPLOADS_DIR_APP / run_id / nombre
        if candidato.is_file() and not candidato.is_symlink():
            return candidato
        metadata = leer_json(BASE_DIR / "outputs" / "runs" / run_id / "metadata_lote.json")
        anterior = str(metadata.get("parent_run_id") or "").strip()
        if anterior and anterior not in vistos:
            ids.append(anterior)
    return None


def preparar_dataframe_con_links_pdf(filas):
    """Restaura la columna Archivo como enlaces a PDFs en otra pestaña."""
    dataframe = pd.DataFrame(filas).copy()
    column_config = {}
    if dataframe.empty or "Archivo" not in dataframe.columns:
        return dataframe, column_config

    enlaces = []
    for nombre in dataframe["Archivo"].tolist():
        original = _resolver_pdf_original(nombre)
        if original is None:
            enlaces.append("")
            continue
        try:
            enlaces.append(publicar_pdf(original, BASE_DIR))
        except (OSError, ValueError) as exc:
            st.warning(f"No fue posible publicar un PDF para abrirlo: {exc}")
            enlaces.append("")

    # Si alguna ruta no se puede resolver, no convertir esa columna en enlaces
    # incompletos. Los nombres originales seguirán visibles como texto.
    if not enlaces or not all(enlaces):
        return dataframe, column_config
    dataframe["Archivo"] = enlaces
    column_config["Archivo"] = st.column_config.LinkColumn(
        "Archivo",
        width="large",
        help="Haz clic en el nombre para abrir el PDF original en otra pestaña.",
        display_text=r"app/static/pdfs/[a-f0-9]+/(.*)",
    )
    return dataframe, column_config


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


TABLAS_RESUMEN_RENDERIZADAS = 0


def _configuracion_ancho_resumen(column_config: dict) -> dict:
    """Evita que nombres de programas enormes desplacen Plan fuera de pantalla."""
    config = dict(column_config)
    # El orden inicial hace que Plan aparezca después de los dos programas.
    # Las anchuras se expresan en px para no autosize por textos extensos.
    anchos = {
        "Archivo": 245,
        "Prompt usado": 105,
        "Programa origen": 205,
        "Programa al que aspira": 240,
        "Plan": 66,
        "Nivel": 95,
        "Estado": 118,
        "Error": 115,
        "Créditos homologados": 148,
        "Duración": 95,
        "Fase actual": 110,
    }
    for columna, ancho in anchos.items():
        if columna == "Archivo" and "Archivo" in config:
            config["Archivo"] = st.column_config.LinkColumn(
                "Archivo", width=ancho,
                help="Haz clic para abrir el PDF en otra pestaña.",
                display_text=r"app/static/pdfs/[a-f0-9]+/(.*)",
            )
        elif columna == "Archivo":
            config["Archivo"] = st.column_config.Column("Archivo", width=ancho)
        else:
            config[columna] = st.column_config.Column(
                columna, width=ancho,
                help=("El ancho es compacto para mantener Plan a la vista. "
                      "El contenido completo se conserva en el resultado y el CSV."),
            )
    return config


def _disposicion_guardada_resumen(sufijo: str) -> list[str]:
    """Lee el orden global. Los controles guardan cada movimiento inmediatamente."""
    try:
        orden, revision, proyecto = leer_orden()
    except (ErrorSincronizacion, ValueError) as exc:
        st.warning(
            f"No se pudo recuperar el orden global de columnas: {exc}. "
            "Se mostrará el orden preferido predeterminado."
        )
        return list(ORDEN_PREDETERMINADO)

    with st.expander("⚙️ Personalizar el orden de las columnas", expanded=False):
        st.caption(
            "Elige una columna y muévela con las flechas. Cada cambio se guarda "
            "automáticamente para las siguientes tandas y para el otro Cloud Shell. "
            "Arrastrar columnas directamente dentro de la tabla solo cambia la vista "
            "del navegador y no se puede guardar desde Streamlit."
        )
        sel_col, mover_izq, mover_der, mover_inicio = st.columns([3.5, 1, 1, 1.4])
        with sel_col:
            columna = st.selectbox(
                "Columna que quieres mover",
                options=orden,
                index=orden.index("Plan") if "Plan" in orden else 0,
                key=f"seleccion_columna_resumen_{sufijo}",
            )
        posicion = orden.index(columna)
        acciones = (
            (mover_izq, "←", "izquierda", posicion == 0),
            (mover_der, "→", "derecha", posicion == len(orden) - 1),
            (mover_inicio, "Al inicio", "inicio", posicion == 0),
        )
        for destino, etiqueta, movimiento, inhabilitado in acciones:
            with destino:
                pulsado = st.button(
                    etiqueta,
                    help=f"Mover {columna}: {movimiento}",
                    key=f"mover_columna_{movimiento}_{sufijo}",
                    disabled=inhabilitado,
                    use_container_width=True,
                )
                if pulsado:
                    try:
                        nuevo = mover_columna(orden, columna, movimiento)
                        guardar_orden(nuevo, revision)
                    except (ValueError, ErrorSincronizacion) as exc:
                        st.error(f"No se pudo guardar el orden: {exc}")
                    else:
                        st.rerun()
        st.caption(
            "Orden global en Firestore." if proyecto
            else "Orden guardado en este Cloud Shell (Firestore no configurado)."
        )
        if st.button(
            "Restablecer distribución recomendada",
            key=f"restablecer_columnas_resumen_{sufijo}",
        ):
            try:
                guardar_orden(list(ORDEN_PREDETERMINADO), revision)
            except (ValueError, ErrorSincronizacion) as exc:
                st.error(f"No se pudo restablecer el orden: {exc}")
            else:
                st.rerun()
    return orden


def renderizar_tabla_resumen_planes(filas) -> None:
    global TABLAS_RESUMEN_RENDERIZADAS
    TABLAS_RESUMEN_RENDERIZADAS += 1
    sufijo = str(TABLAS_RESUMEN_RENDERIZADAS)
    try:
        configuracion, _, _ = leer_configuracion(PROGRAMAS_PLANES_PATH)
    except ErrorSincronizacion as exc:
        st.error(f"Sincronización de planes no disponible: {exc}")
        st.stop()
    conteo = resumir_validacion_planes(filas, configuracion)
    requieren_revision = conteo["incorrectos"] + conteo["sin_configuracion"]
    dataframe, column_config = preparar_dataframe_con_links_pdf(filas)
    orden = _disposicion_guardada_resumen(sufijo)
    columnas = ordenar_visibles(dataframe.columns, orden)
    dataframe = dataframe[columnas]
    column_config = _configuracion_ancho_resumen(column_config)

    st.caption(
        f"🟢 {conteo['correctos']} plan(es) coinciden · "
        f"🟠 {requieren_revision} requieren revisión. "
        "El naranja indica un plan diferente o un programa aún no configurado."
    )
    st.dataframe(
        estilizar_tabla_planes(dataframe, configuracion),
        use_container_width=True,
        hide_index=True,
        column_order=columnas,
        column_config=column_config,
    )


def renderizar_tabla_errores_con_links(filas) -> None:
    dataframe, column_config = preparar_dataframe_con_links_pdf(filas)
    try:
        orden, _, _ = leer_orden()
    except (ErrorSincronizacion, ValueError):
        orden = list(ORDEN_PREDETERMINADO)
    columnas = ordenar_visibles(dataframe.columns, orden)
    dataframe = dataframe[columnas]
    st.dataframe(
        dataframe,
        use_container_width=True,
        hide_index=True,
        column_order=columnas,
        column_config=_configuracion_ancho_resumen(column_config),
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

_OLD_OPERATIONAL_CONFIG_MARKER = '''timeouts_locales = cargar_timeouts_persistentes()
timeouts_persistidos = _seleccionar_global("timeouts", timeouts_locales)

with st.container():
'''

_NEW_OPERATIONAL_CONFIG_BLOCK = '''timeouts_locales = cargar_timeouts_persistentes()
timeouts_persistidos = _seleccionar_global("timeouts", timeouts_locales)

# La página principal solo muestra controles de ejecución diaria.
# Programas/planes y retención se editarán desde sus páginas laterales.
try:
    preferencias_operativas, revision_operativa, proyecto_operativo = leer_preferencias()
    error_operativa = None
except (ErrorSincronizacion, ValueError) as exc:
    preferencias_operativas = {"procesos_predeterminados": 4, "retencion_dias": 7,
                              "retencion_pdfs_dias": 3}
    revision_operativa = None
    error_operativa = str(exc)

# El mantenimiento automático sigue ejecutándose al usar la página principal.
if not error_operativa:
    try:
        estado_mantenimiento = mantenimiento_periodico(
            BASE_DIR, dias=int(preferencias_operativas.get("retencion_pdfs_dias", 3))
        )
    except (ValueError, ErrorSincronizacion, OSError) as error_mantenimiento:
        st.warning(f"No fue posible comprobar la limpieza automática: {error_mantenimiento}")
    else:
        if estado_mantenimiento.get("errores"):
            st.warning(
                f"Historial y limpieza: {len(estado_mantenimiento['errores'])} lote(s) "
                "no se eliminaron para proteger los originales."
            )

with st.container():
    if "max_workers_opencode_ui_base" not in st.session_state:
        st.session_state["max_workers_opencode_ui_base"] = int(
            preferencias_operativas["procesos_predeterminados"]
        )

    col_procesos, col_planes, col_ajustes = st.columns([1.15, 1, 1], gap="medium")
    with col_procesos:
        max_workers_opencode = st.slider(
            "Procesos simultáneos", min_value=1, max_value=20, step=1,
            key="max_workers_opencode_ui_base",
            disabled=bool(error_operativa),
            help="Concurrencia del lote actual; cambia el predeterminado desde Configuración operativa.",
        )
    with col_planes:
        st.page_link(
            "pages/05_Programas_y_planes.py", label="🎓 Programas y planes",
            help="Editar catálogo y equivalencias desde una página dedicada.",
        )
    with col_ajustes:
        st.page_link(
            "pages/06_Configuracion_operativa.py", label="⚙️ Configuración operativa",
            help="Retención, predeterminado global y almacenamiento.",
        )
    if error_operativa:
        st.error(f"Preferencias compartidas no disponibles: {error_operativa}")
    elif max_workers_opencode > 6:
        st.caption("Alta concurrencia: aumenta la posibilidad de límites de API. "
                   "En OpenRouter se aplica un límite protector de 2 solicitudes.")

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