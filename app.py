"""Entry point: junta "Despliegues AID" (core/, ui/) y "Extracción /
Inventario" (python_pipeline/, ui/inventario.py) en un solo Streamlit."""
from pathlib import Path

import streamlit as st

from ui import run_app

_icon_path = Path(__file__).parent / "img" / "logo1.png"
st.set_page_config(
    page_title="AID - Gestión de Flujos",
    page_icon=str(_icon_path) if _icon_path.exists() else "",
    layout="wide",
    initial_sidebar_state="collapsed"
)

run_app()
