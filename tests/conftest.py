"""Fixtures de test.

Con app.py ya partido en módulos (config, analysis, ado_client, reports, guide,
utils, ui/), los tests importan la lógica directo — ya no hace falta compilar
el código fuente a mano ni inyectar un `streamlit` de mentira como antes.

Nota: `analysis.py` sí importa `streamlit` de verdad (lo usa `cargar_json`
para avisar de JSON inválido con `st.warning`) — pero al no correr dentro de
`streamlit run`, esas llamadas simplemente no hacen nada visible aquí.
"""
from pathlib import Path

import pytest

import core.analysis as analysis


@pytest.fixture(scope="session")
def appmod():
    """Alias histórico: expone el módulo de lógica pura (`analysis`)."""
    return analysis


@pytest.fixture()
def fixtures_dir():
    return Path(__file__).resolve().parent.parent / "Backlog_Dealer" / "demo-project_Demo Area_Sprint 253"
