"""Orquesta el render de la app: estilos -> header -> dos secciones
independientes en pestañas ("Despliegues AID" y "Extracción / Inventario").

Cada sección tiene su propio "core" (core/ y python_pipeline/
respectivamente) y no comparte credenciales ni tablas AWS entre sí — conviven
en la misma app pero una puede fallar sin afectar a la otra.
"""
import streamlit as st

from ui import styles, header, ingest, dashboard, backlog, hu_detail, aws_console, inventario
from core.utils import get_sprints


def _render_despliegues_aid():
    sprints_locales = get_sprints()

    ingest.render_paso1_paso2(sprints_locales)
    st.divider()

    resultados, sprint_activo = dashboard.cargar_resultados()
    dashboard.render_kpis_y_progreso(resultados)

    st.divider()
    backlog.render_excel_card()
    backlog.render_tabla_resumen(resultados)

    hu_detail.render_hu_detail(resultados, sprint_activo)
    aws_console.render_aws_console(resultados)


def run_app():
    styles.inject_css()
    styles.inject_scroll_restore()
    header.render_header()

    # st.segmented_control (no st.tabs) a propósito: varias pantallas de
    # "Despliegues AID" usan st.stop() cuando no hay datos cargados (el caso
    # más común al abrir la app) — eso corta TODO el script, no solo el
    # contenido visual de esa pestaña. st.segmented_control se ve y se usa
    # como pestañas reales, pero es un widget de selección como el radio: solo
    # se ejecuta la rama elegida, así que un st.stop() de una sección nunca
    # apaga la otra.
    seccion = st.segmented_control(
        "Sección", ["Despliegues AID", "Extracción / Inventario"],
        default="Despliegues AID", label_visibility="collapsed", key="seccion_app",
        width='stretch',
    )
    st.divider()

    # st.segmented_control permite "deseleccionar" haciendo clic de nuevo en
    # la opción activa (a diferencia de un radio) — en ese caso devuelve None;
    # se mantiene la última sección real en vez de saltar siempre a la primera.
    if seccion is None:
        seccion = st.session_state.get("_ultima_seccion_app", "Despliegues AID")
    st.session_state["_ultima_seccion_app"] = seccion

    if seccion == "Despliegues AID":
        _render_despliegues_aid()
    else:
        inventario.render_inventario()
