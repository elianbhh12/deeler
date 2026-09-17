"""
Punto de entrada de "Despliegues AID". La app junta, en un solo Streamlit,
las dos herramientas de AID (ver ui.run_app -> ui/__init__.py):

  - Despliegues AID: valida y despliega HU (Azure DevOps -> validaciones ->
    AWS). Es la herramienta original de este proyecto; su "core" vive en
    core/ y su "ui" en ui/ (dashboard.py, hu_detail.py, aws_console.py, etc).
  - Extracción / Inventario: descarga e inventaría config-control,
    text-analyzer y events-manager (UDZ) desde DynamoDB. Su "core" es
    python_pipeline/ (traído tal cual del proyecto hermano "flujosscript",
    sin tocar su lógica interna); su "ui" es ui/inventario.py.

A diferencia de como se integró esto en el proyecto "flujosscript" (que
carga banco/ui como paquete externo vía sys.path, porque son dos repos
separados), acá python_pipeline/ vive nativo dentro de este mismo proyecto
-- mismo intérprete, mismo requirements.txt, sin parches de sys.path.

Cada herramienta es independiente: tiene su propio archivo de credenciales
AWS (AWS_CRED_FILE vs PIPELINE_CRED_FILE, ver core/config.py) y no comparte
tablas ni estado entre sí. ui/__init__.py::run_app() elige cuál mostrar con
un st.segmented_control (no st.tabs) -- varias pantallas de "Despliegues
AID" usan st.stop() cuando no hay datos, y eso corta TODO el script; con un
selector, solo se ejecuta la rama elegida, así que una sección nunca apaga
la otra.
"""
from pathlib import Path

import streamlit as st

from ui import run_app

_icon_path = Path(__file__).parent / "img" / "logo1.png"
st.set_page_config(
    page_title="Despliegues AID",
    page_icon=str(_icon_path) if _icon_path.exists() else "",
    layout="wide",
    initial_sidebar_state="collapsed"
)

run_app()
