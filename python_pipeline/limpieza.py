"""Limpieza manual de descargas/<tabla>/<ambiente>/<fecha>/ -- no corre sola
en el pipeline. Lo resumido ya vive en maestro_<ambiente>.xlsx/historial/."""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from . import config

logger = logging.getLogger(__name__)


@dataclass
class ResumenDescargas:
    carpetas_de_fecha: int = 0
    bytes_totales: int = 0

    @property
    def mb_totales(self) -> float:
        return round(self.bytes_totales / (1024 * 1024), 1)


def _tamano_carpeta(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def _carpetas_de_fecha() -> List[Path]:
    if not config.DESCARGAS_DIR.is_dir():
        return []
    carpetas = []
    for tabla_dir in config.DESCARGAS_DIR.iterdir():
        if not tabla_dir.is_dir():
            continue
        for ambiente_dir in tabla_dir.iterdir():
            if not ambiente_dir.is_dir():
                continue
            for fecha_dir in ambiente_dir.iterdir():
                if fecha_dir.is_dir():
                    carpetas.append(fecha_dir)
    return carpetas


def medir_descargas() -> ResumenDescargas:
    carpetas = _carpetas_de_fecha()
    return ResumenDescargas(
        carpetas_de_fecha=len(carpetas),
        bytes_totales=sum(_tamano_carpeta(c) for c in carpetas),
    )


def limpiar_descargas_viejas(dias_retener: int = 30, dry_run: bool = False) -> dict:
    """dry_run=True: no borra nada, solo devuelve qué borraría."""
    corte = datetime.now() - timedelta(days=dias_retener)
    borradas: List[str] = []
    bytes_liberados = 0
    conservadas = 0

    for fecha_dir in _carpetas_de_fecha():
        try:
            fecha = datetime.strptime(fecha_dir.name, config.DATE_FORMAT)
        except ValueError:
            # Nombre de carpeta que no es una fecha -- no se toca.
            conservadas += 1
            continue

        if fecha >= corte:
            conservadas += 1
            continue

        tamano = _tamano_carpeta(fecha_dir)
        borradas.append(str(fecha_dir))
        bytes_liberados += tamano
        if not dry_run:
            shutil.rmtree(fecha_dir, ignore_errors=True)

    if not dry_run:
        logger.info(
            "Limpieza de descargas: %s carpetas borradas (%.1f MB liberados), %s conservadas.",
            len(borradas), bytes_liberados / (1024 * 1024), conservadas,
        )

    return {"borradas": borradas, "bytes_liberados": bytes_liberados, "conservadas": conservadas}
