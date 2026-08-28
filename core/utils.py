"""Utilidades generales: nombres de archivo/sprint, usuario actual, abrir carpeta/archivo."""
import os
import re
import subprocess
from pathlib import Path

import streamlit as st

from .config import ROOT_FOLDER, MI_WARNING, MI_ERROR


def safe_name(text: str, max_len=80):
    text = re.sub(r"[\\/:*?\"<>|]", "_", text or "")
    return text[:max_len].strip() or "sin_titulo"


def obtener_usuario_actual() -> str:
    """Usuario de Windows de la sesión donde corre esta app.

    Sirve como identificación básica para trazabilidad ('quién corrió el
    análisis / quién aprobó'), NO como control de acceso: cualquiera con
    sesión abierta en esta máquina puede aparecer como este usuario.
    """
    try:
        return os.getlogin()
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "desconocido"


def sprint_display_name(folder_name: str) -> str:
    """Extrae el número del sprint y lo muestra en formato "Sprint XXX (Sprint Vicepresidencia...)"""
    match = re.search(r"Sprint\s*(\d+)", folder_name, re.IGNORECASE)
    sprint_num = match.group(1) if match else "?"
    match2 = re.search(r"(Sprint\s*\d+)", folder_name, re.IGNORECASE)
    sprint_name = match2.group(1) if match2 else folder_name
    return f"Sprint {sprint_num}"


def get_sprints():
    root = Path(ROOT_FOLDER)
    if not root.exists():
        return []
    return sorted([d for d in root.iterdir() if d.is_dir()], reverse=True)


def abrir_carpeta(ruta: Path):
    """Abre la carpeta en el explorador de archivos"""
    if not ruta.exists():
        st.warning(f"La carpeta no existe: `{ruta}`", icon=MI_WARNING)
        return False
    try:
        subprocess.Popen(["explorer", str(ruta)])
        return True
    except Exception as e:
        st.error(f"No se pudo abrir la carpeta: {e}", icon=MI_ERROR)
        return False


def abrir_archivo(ruta: Path):
    """Abre un archivo con su aplicación predeterminada"""
    if not ruta.exists():
        st.warning(f"El archivo no existe: `{ruta}`", icon=MI_WARNING)
        return False
    try:
        os.startfile(ruta)
        return True
    except Exception as e:
        st.error(f"No se pudo abrir el archivo: {e}", icon=MI_ERROR)
        return False
