"""Orquesta el render: estilos -> header -> selector entre "Despliegues AID"
y "Extracción / Inventario"."""
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

    # No st.tabs: st.stop() en pantallas de "Despliegues AID" cortaría toda
    # la app. Con un selector solo corre la rama elegida.
    seccion = st.segmented_control(
        "Sección", ["Despliegues AID", "Extracción / Inventario"],
        default="Despliegues AID", label_visibility="collapsed", key="seccion_app",
        width='stretch',
    )
    st.divider()

    # Un segundo clic en la opción activa deselecciona (devuelve None).
    if seccion is None:
        seccion = st.session_state.get("_ultima_seccion_app", "Despliegues AID")
    st.session_state["_ultima_seccion_app"] = seccion

    if seccion == "Despliegues AID":
        _render_despliegues_aid()
    else:
        inventario.render_inventario()
