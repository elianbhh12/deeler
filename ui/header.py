"""Header de la app y el stepper del pipeline (Traer -> Analizar -> Revisar)."""
import base64
from pathlib import Path

import streamlit as st


def render_header():
    _logo_path = Path(__file__).resolve().parent.parent / "img"
    _logo_files = list(_logo_path.glob("*")) if _logo_path.exists() else []
    _logo_img_tag = ""
    if _logo_files:
        _lf = _logo_files[0]
        _ext = _lf.suffix.lower().lstrip(".")
        _mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "svg": "image/svg+xml", "webp": "image/webp"}.get(_ext, "image/png")
        _logo_b64 = base64.b64encode(_lf.read_bytes()).decode()
        _logo_img_tag = f'<img src="data:{_mime};base64,{_logo_b64}" style="height:48px;width:auto;object-fit:contain;border-radius:8px" alt="logo"/>'

    st.markdown(f"""
    <div class="app-header">
        <div style="display:flex;align-items:center;gap:14px">{_logo_img_tag}
            <div>
                <div class="app-header-title">AID Flujos Dealer</div>
                <div class="app-header-subtitle">Validación técnica automatizada de componentes TA, AID y UDZ</div>
            </div>
        </div>
        <div class="app-badge">Gate de calidad · Pre-PDN</div>
    </div>
    """, unsafe_allow_html=True)


def render_stepper(sprints_locales, hay_resultados: bool):
    paso1_cls = "done" if sprints_locales else "active"
    paso2_cls = "done" if hay_resultados else ("active" if sprints_locales else "")
    paso3_cls = "active" if hay_resultados else ""
    paso4_cls = "active" if hay_resultados else ""

    st.markdown(f"""
    <div class="pipeline-stepper">
        <div class="pipeline-step {paso1_cls}"><span class="pipeline-step-num">1</span> Traer HU de ADO</div>
        <span class="pipeline-arrow">→</span>
        <div class="pipeline-step {paso2_cls}"><span class="pipeline-step-num">2</span> Analizar componentes</div>
        <span class="pipeline-arrow">→</span>
        <div class="pipeline-step {paso3_cls}"><span class="pipeline-step-num">3</span> Subir a AWS QA</div>
        <span class="pipeline-arrow">→</span>
        <div class="pipeline-step {paso4_cls}"><span class="pipeline-step-num">4</span> Revisar y aprobar para PDN</div>
    </div>
    """, unsafe_allow_html=True)
