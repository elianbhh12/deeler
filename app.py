"""Punto de entrada de la app. La lógica vive en core/ y la interfaz en ui/
(ver README.md)."""
from pathlib import Path

import streamlit as st

from ui import run_app

_icon_path = Path(__file__).parent / "img" / "logo1.png"
st.set_page_config(
    page_title="AID Flujos Dealer",
    page_icon=str(_icon_path) if _icon_path.exists() else "",
    layout="wide",
    initial_sidebar_state="collapsed"
)

run_app()
