"""
Paso 5: compara los JSON de una carpeta R3 contra Orden_RE_Base.txt (lista
de nombres ya catalogados) y saca los que son nuevos, con las mismas
columnas del reporte maestro. Puerto de nuevos_r3_vs_orden.py.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, Optional

from . import common

logger = logging.getLogger(__name__)

HEADER = [
    "Nombre de los JSONs", "Nombre TA Config", "Nombre del subtipo",
    "Cantidad de archivos con ese subtipo", "Proceso", "s3_path",
    "Responsable ciencia", "Usuario responsable", "Lider responsable",
    "Unidad de Negocio", "Area", "VP Nivel 2", "Observaciones", "Dynamo Delete",
]


def _read_orden(orden_file: Path) -> set:
    if not orden_file.exists():
        raise FileNotFoundError(
            f"No existe el archivo de orden: {orden_file}\n"
            "Este archivo debe contener, una por linea, los nombres de JSON "
            "R3 ya catalogados (el baseline vigente)."
        )
    return {line.strip() for line in orden_file.read_text(encoding="utf-8").splitlines() if line.strip()}


def _read_detalle(detalle_csv: Optional[Path]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    if not detalle_csv or not detalle_csv.exists():
        return out
    with detalle_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        header = next(reader, None)
        if not header:
            return out
        for row in reader:
            if len(row) < 6 or not row[0].strip():
                continue
            out[row[0].strip()] = {
                "ta_config": row[1].strip(), "subtipo": row[2].strip(),
                "cantidad": row[3].strip(), "observaciones": row[4].strip(),
                "s3_path": row[5].strip(),
            }
    return out


def generate(r3_dir: Path, orden_file: Path, out_csv: Path, detalle_csv: Optional[Path] = None) -> int:
    orden_actual = _read_orden(orden_file)
    detalle = _read_detalle(detalle_csv)

    r3_info = {}
    for json_file, data in common.load_json_files(r3_dir):
        r3_info[json_file.name] = {
            "subtipo": common.get_tipo_documento(data),
            "proceso": common.get_proceso(data),
            "s3_path": str(data.get("s3_path") or ""),
        }

    conteos_subtipo: Dict[str, int] = {}
    for info in r3_info.values():
        clave = common.normalize_text(info["subtipo"])
        conteos_subtipo[clave] = conteos_subtipo.get(clave, 0) + 1

    nuevos = sorted(name for name in r3_info if name not in orden_actual)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";", lineterminator="\n")
        writer.writerow(HEADER)
        for nombre in nuevos:
            info = r3_info[nombre]
            det = detalle.get(nombre, {})
            subtipo = det.get("subtipo") or info["subtipo"]
            cantidad = det.get("cantidad") or str(conteos_subtipo.get(common.normalize_text(subtipo), 1))
            writer.writerow([
                nombre, det.get("ta_config", ""), subtipo, cantidad,
                info["proceso"], det.get("s3_path") or info["s3_path"],
                "", "", "", "", "", "", det.get("observaciones", ""), "",
            ])

    logger.info("Nuevos vs %s: %s", orden_file.name, len(nuevos))
    return len(nuevos)
