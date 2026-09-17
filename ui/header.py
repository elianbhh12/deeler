"""Header de la app y el stepper del pipeline (Traer -> Analizar -> Revisar)."""
import base64
from pathlib import Path

import streamlit as st


def render_header():
    _logo_path = Path(__file__).resolve().parent.parent / "img"
    # .ico queda afuera: es para el acceso directo, no para <img> inline.
    _logo_files = sorted(
        f for f in (_logo_path.glob("*") if _logo_path.exists() else [])
        if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".webp")
    )
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
                <div class="app-header-title">AID - Gestión de Flujos</div>
                <div class="app-header-subtitle">Despliegues AID y Extracción / Inventario</div>
            </div>
        </div>
        <div class="app-badge">Plataforma interna</div>
    </div>
    """, unsafe_allow_html=True)
