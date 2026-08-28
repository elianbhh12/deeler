"""Paso 1 (traer HU de ADO) y Paso 2 (analizar un sprint ya descargado)."""
import re
from pathlib import Path
from datetime import datetime

import streamlit as st

from core.config import (
    ITERATION_PATH, ROOT_FOLDER, SPRINTS_FRECUENTES, _sprint_default_num,
    MI_DOWNLOAD, MI_ERROR, MI_OK, MI_WARNING, MI_INFO, MI_REFRESH, MI_FOLDER,
)
from core.ado_client import descargar_hu
from core.analysis import analizar_sprint
from core.utils import sprint_display_name, abrir_carpeta


def render_paso1_paso2(sprints_locales):
    col_paso1, col_paso2 = st.columns([1, 1], gap="medium")

    with col_paso1:
        st.markdown("""<div class="step-card-label">Paso 1 <span class="step-sub">— traer HU nuevas desde Azure DevOps</span></div>""", unsafe_allow_html=True)
        st.markdown("""<div class="step-card-help">Sprint a consultar en ADO (por número)</div>""", unsafe_allow_html=True)

        _opts = SPRINTS_FRECUENTES
        _default_idx = _opts.index(_sprint_default_num) if _sprint_default_num in _opts else 0

        sprint_quick = st.selectbox(
            "Sprint a consultar en ADO",
            options=_opts,
            index=_default_idx,
            format_func=lambda x: f"Sprint {x}",
            label_visibility="collapsed"
        )

        base_path = ITERATION_PATH or ""
        if "2026" in base_path:
            parts = base_path.split("\\")
            for i, p in enumerate(parts):
                if p.startswith("Sprint"):
                    parts[i] = f"Sprint {sprint_quick}"
                    sprint_input = "\\".join(parts)
                    break
            else:
                sprint_input = base_path
        else:
            sprint_input = base_path

        if st.button("Descargar HU", width='stretch', type="primary", key="btn_descargar", icon=MI_DOWNLOAD):
            if not sprint_input:
                st.error("Selecciona un sprint", icon=MI_ERROR)
            else:
                with st.spinner("Descargando desde ADO..."):
                    n = descargar_hu(sprint_input)
                if n > 0:
                    st.success(f"{n} HU descargadas", icon=MI_OK)
                    st.rerun()
                else:
                    st.warning("No hay HU con PIA en este sprint", icon=MI_WARNING)

    with col_paso2:
        _sprint_activo_now = st.session_state.get("sprint_activo", "")
        _last_analyzed      = st.session_state.get("_last_analyzed", "")

        # Label con indicador de estado
        if _sprint_activo_now:
            _snum = re.search(r"Sprint\s*(\d+)", _sprint_activo_now, re.IGNORECASE)
            _snum = _snum.group(1) if _snum else _sprint_activo_now.split("_")[-1]
            _sub = f"Sprint {_snum} cargado"
            if _last_analyzed:
                _sub += f" — analizado {_last_analyzed}"
        else:
            _sub = "analizar un sprint ya descargado"

        st.markdown(f"""<div class="step-card-label">Paso 2 <span class="step-sub">— {_sub}</span></div>""", unsafe_allow_html=True)
        st.markdown("""<div class="step-card-help">Sprint local ya descargado (carpeta en disco)</div>""", unsafe_allow_html=True)

        if sprints_locales:
            sprint_display = {sprint_display_name(d.name): d.name for d in sprints_locales}
            sprint_sel_display = st.selectbox(
                "Sprint local ya descargado",
                list(sprint_display.keys()),
                label_visibility="collapsed"
            )
            sprint_sel_name = sprint_display.get(sprint_sel_display)
        else:
            sprint_sel_name = None
            st.info("Descarga un sprint primero en el Paso 1 para poder analizar.", icon=MI_INFO)

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            _btn_label = "Re-analizar sprint" if _sprint_activo_now else "Analizar sprint"
            if st.button(_btn_label, width='stretch', type="primary", key="btn_analizar", disabled=not sprint_sel_name, icon=MI_REFRESH):
                sprint_path = Path(ROOT_FOLDER) / sprint_sel_name
                with st.spinner("Analizando TA, AID, UDZ..."):
                    resultados_new = analizar_sprint(sprint_path)
                st.success(f"{len(resultados_new)} HU analizadas", icon=MI_OK)
                st.session_state["resultados"]     = resultados_new
                st.session_state["sprint_activo"]  = sprint_sel_name
                st.session_state["_excel_pending"] = True
                st.session_state["_last_analyzed"] = datetime.now().strftime("%H:%M:%S")
                st.rerun()

        with col_btn2:
            sprint_path_for_btn = Path(ROOT_FOLDER) / sprint_sel_name if sprint_sel_name else None
            _carpeta_existe = bool(sprint_path_for_btn and sprint_path_for_btn.exists())
            if st.button("Abrir carpeta", width='stretch', key="btn_abrir_sprint", icon=MI_FOLDER, disabled=not _carpeta_existe) and sprint_path_for_btn:
                abrir_carpeta(sprint_path_for_btn)
                st.success("Carpeta abierta", icon=MI_OK)
