"""
Paso 2: cruza use_case (R3) contra cu_name (text-analyzer).

Diferencia clave frente a compare_r3_vs_text_analyzer.sh:
  - Sin jq/awk/mktemp/trap: se usan dicts y csv.writer de la libreria
    estandar.
  - La columna "Comparte TA" (cu_name usado por mas de un R3) se calcula
    agrupando en un dict, en vez del `awk` con gsub que intentaba "restar"
    el propio nombre de una cadena concatenada; ese gsub podia fallar si
    un nombre de archivo era subcadena de otro (p.ej. "X.json" dentro de
    "OTRO_X.json"). Aqui se compara por igualdad de elementos de lista,
    no por texto, asi que ese caso queda resuelto correctamente.
"""
from __future__ import annotations

import csv
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from . import common, config

logger = logging.getLogger(__name__)

CLASSIFIED_HEADER = ["Nombre de los JSONs", "Nombre TA config (cu_name)", "Nombre del subtipo", "Comparte TA", "Ruta JSON R3"]
DETAIL_HEADER = ["Nombre de los JSONs", "Nombre TA config", "Nombre del subtipo", "Cantidad de archivos con ese subtipo", "Observaciones", "Ruta JSON R3"]


@dataclass
class R3Row:
    name: str
    use_case: str
    subtipo: str
    s3_path: str
    matched: bool
    observation: str = ""


def _load_ta_by_cuname(ta_dir: Path) -> Dict[str, Path]:
    mapping: Dict[str, Path] = {}
    for json_file, data in common.load_json_files(ta_dir):
        cu_name = data.get("cu_name")
        if cu_name:
            mapping[str(cu_name)] = json_file
    return mapping


def compare(r3_dir: Path, ta_dir: Path, output_dir: Path) -> dict:
    if not r3_dir.is_dir():
        raise FileNotFoundError(f"No existe el directorio R3: {r3_dir}")
    if not ta_dir.is_dir():
        raise FileNotFoundError(f"No existe el directorio Text Analyzer: {ta_dir}")

    classified_dir = output_dir / "clasificados"
    unclassified_dir = output_dir / "no_clasificados"
    classified_dir.mkdir(parents=True, exist_ok=True)
    unclassified_dir.mkdir(parents=True, exist_ok=True)

    ta_by_cuname = _load_ta_by_cuname(ta_dir)
    if not ta_by_cuname:
        logger.warning("No se encontraron cu_name en %s", ta_dir)

    rows: List[R3Row] = []
    missing_use_case = 0
    for json_file, data in common.load_json_files(r3_dir):
        name = common.sanitize_csv_field(json_file.name)
        use_case = common.sanitize_csv_field(common.get_use_case(data))
        subtipo = common.sanitize_csv_field(common.get_subtipo_workflow_variables(data))
        s3_path = common.sanitize_csv_field(str(data.get("s3_path") or ""))

        if not use_case:
            missing_use_case += 1
            observation = config.MANUAL_OBSERVATIONS.get(json_file.name, "Validar Manualmente")
            rows.append(R3Row(name, "SIN_USE_CASE", subtipo, s3_path, matched=False, observation=observation))
            continue

        if use_case in ta_by_cuname:
            observation = "Validar Manualmente" if subtipo == "REVISAR_MANUAL" else ""
            rows.append(R3Row(name, use_case, subtipo, s3_path, matched=True, observation=observation))
        else:
            observation = config.MANUAL_OBSERVATIONS.get(json_file.name, "Validar Manualmente")
            rows.append(R3Row(name, use_case, subtipo, s3_path, matched=False, observation=observation))

    matched_rows = [r for r in rows if r.matched]
    unmatched_rows = [r for r in rows if not r.matched]

    # "Comparte TA": cu_name usado por mas de un R3 matched.
    by_cuname: Dict[str, List[str]] = defaultdict(list)
    for row in matched_rows:
        by_cuname[row.use_case].append(row.name)

    classified_file = classified_dir / "ta_cu_name.txt"
    with classified_file.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";", lineterminator="\n")
        writer.writerow(CLASSIFIED_HEADER)
        for row in sorted(matched_rows, key=lambda r: r.name):
            group = by_cuname[row.use_case]
            comparte = ""
            if len(group) > 1:
                others = ", ".join(n for n in group if n != row.name)
                comparte = f"Si: {others}"
            writer.writerow([row.name, row.use_case, row.subtipo, comparte, row.s3_path])

    unclassified_file = unclassified_dir / "r3_sin_ta.txt"
    with unclassified_file.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";", lineterminator="\n")
        writer.writerow(["Nombre de los JSONs", "Nombre TA config faltante/SIN_USE_CASE", "Nombre del subtipo", "Observaciones", "Ruta JSON R3"])
        for row in sorted(unmatched_rows, key=lambda r: r.name):
            writer.writerow([row.name, row.use_case, row.subtipo, row.observation, row.s3_path])

    # Detalle: todos los R3, con cantidad de archivos por subtipo (sobre el total).
    subtype_counts = Counter(row.subtipo for row in rows)
    detail_file = output_dir / "detalle_r3_vs_ta.csv"
    with detail_file.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";", lineterminator="\n")
        writer.writerow(DETAIL_HEADER)
        for row in sorted(rows, key=lambda r: r.name):
            writer.writerow([row.name, row.use_case, row.subtipo, subtype_counts[row.subtipo], row.observation, row.s3_path])

    summary = {
        "total_r3": len(rows),
        "total_ta_con_cuname": len(ta_by_cuname),
        "matched": len(matched_rows),
        "unmatched": len(unmatched_rows),
        "missing_use_case": missing_use_case,
        "classified_file": classified_file,
        "unclassified_file": unclassified_file,
        "detail_file": detail_file,
    }
    logger.info(
        "Comparacion finalizada: %s R3 analizados, %s con Text Analyzer, %s por revisar",
        summary["total_r3"], summary["matched"], summary["unmatched"],
    )
    return summary
