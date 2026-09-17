"""
Matriz de ambientes: por cada flujo, en que ambientes (qa/pdn/dev) esta
presente, para responder directamente "esto que ya esta en pdn, esta
tambien en qa?" sin tener que abrir un Excel por ambiente y comparar a mano.

Es ACUMULABLE: a diferencia del reporte_completo.xlsx (que es una foto de
una sola corrida), este estado se guarda en historial/matriz_ambientes.json
y cada corrida de un ambiente lo actualiza sin borrar lo que se sabe de los
otros ambientes. Un flujo que estuvo presente y deja de estarlo no se
borra: queda marcado como "No" (para distinguirlo de un flujo que nunca
se vio en ese ambiente, que queda en blanco).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from . import config

logger = logging.getLogger(__name__)

ESTADO_FILE = config.BASE_DIR / "historial" / "matriz_ambientes.json"


def _load() -> Dict[str, dict]:
    if not ESTADO_FILE.exists():
        return {}
    try:
        return json.loads(ESTADO_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("No se pudo leer %s (%s); se parte de una matriz vacia.", ESTADO_FILE, exc)
        return {}


def _save(data: Dict[str, dict]) -> None:
    ESTADO_FILE.parent.mkdir(parents=True, exist_ok=True)
    ESTADO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def actualizar(environment: str, filas_actuales: List[dict], modo: str = "incremental", fecha: str = None) -> Dict[str, dict]:
    """Marca presentes los flujos de filas_actuales. Solo marca ausentes los
    que faltan en modo "completo" (en incremental no representa la tabla
    entera, mismo criterio que historial.actualizar)."""
    fecha = fecha or datetime.now().strftime(config.DATE_FORMAT)
    data = _load()

    nombres_actuales = {fila["file"] for fila in filas_actuales}

    for fila in filas_actuales:
        entry = data.setdefault(fila["file"], {})
        entry[environment] = {
            "presente": True,
            "subtipo": fila.get("subtipo", ""),
            "ultima_vez": fecha,
        }

    if modo == "completo":
        for flujo, ambientes in data.items():
            if environment in ambientes and flujo not in nombres_actuales:
                ambientes[environment]["presente"] = False

    _save(data)
    logger.info("Matriz de ambientes actualizada (%s, modo=%s): %s flujos conocidos en total.", environment, modo, len(data))
    return data


def cargar_estado() -> Dict[str, dict]:
    return _load()
