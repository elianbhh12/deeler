"""Orquesta el render de la app en el mismo orden que tenía el script original:
estilos -> header -> stepper -> Paso 1/2 -> KPIs/progreso -> Excel + tabla ->
detalle de HU seleccionada -> consola "Subir a AWS".
"""
import streamlit as st

from ui import styles, header, ingest, dashboard, backlog, hu_detail, aws_console
from core.utils import get_sprints


def run_app():
    styles.inject_css()
    styles.inject_scroll_restore()
    header.render_header()

    sprints_locales = get_sprints()
    hay_resultados = bool(st.session_state.get("resultados"))
    header.render_stepper(sprints_locales, hay_resultados)

    ingest.render_paso1_paso2(sprints_locales)
    st.divider()

    resultados, sprint_activo = dashboard.cargar_resultados()
    dashboard.render_kpis_y_progreso(resultados)

    st.divider()
    backlog.render_excel_card()
    backlog.render_tabla_resumen(resultados)

    hu_detail.render_hu_detail(resultados, sprint_activo)
    aws_console.render_aws_console(resultados)
