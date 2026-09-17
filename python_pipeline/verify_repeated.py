"""
Paso 3: agrupa los R3 por tipoDocumento normalizado y reporta cuales
subtipos tienen mas de un archivo asociado (posibles configuraciones
duplicadas). Puerto directo de script/verificar_repetidos.py, reutilizando
las funciones ya centralizadas en common.py.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from . import common

logger = logging.getLogger(__name__)


def _load_target_list(file_path: Path) -> List[str]:
    if not file_path.exists():
        raise FileNotFoundError(f"No existe el archivo de lista: {file_path}")
    names = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if clean and not clean.startswith("#"):
            names.append(clean)
    return names


def verify_repeated(
    r3_path: str,
    out_txt: Path,
    target_list_file: Optional[Path] = None,
) -> dict:
    all_files = list(common.iter_json_files(r3_path))

    missing_files: List[str] = []
    if target_list_file:
        target_names = _load_target_list(target_list_file)
        by_basename: Dict[str, List[tuple]] = {}
        for path, raw in all_files:
            by_basename.setdefault(common.basename(path).lower(), []).append((path, raw))

        selected = []
        for requested in target_names:
            matches = by_basename.get(requested.strip().lower(), [])
            if not matches:
                missing_files.append(requested)
            else:
                selected.extend(matches)
        files = selected
        total_requested = len(target_names)
    else:
        files = all_files
        total_requested = len(all_files)

    grouped: Dict[str, dict] = {}
    parse_errors: List[dict] = []

    for path, raw in files:
        file_name = common.basename(path)
        try:
            data = json.loads(raw)
        except Exception as exc:
            parse_errors.append({"archivo": file_name, "error": str(exc)})
            continue

        tipo_documento = common.get_tipo_documento(data)
        proceso = common.get_proceso(data)
        norm = common.normalize_text(tipo_documento) or "sin tipodocumento"

        group = grouped.setdefault(norm, {"subtipo": tipo_documento, "variantes": set(), "archivos": []})
        group["variantes"].add(tipo_documento)
        group["archivos"].append({"archivo": file_name, "proceso": proceso})

    repeated = [g for g in grouped.values() if len(g["archivos"]) > 1]
    repeated.sort(key=lambda g: (-len(g["archivos"]), common.normalize_text(g["subtipo"])))

    _write_report(out_txt, repeated, missing_files, parse_errors, total_requested, len(files))

    summary = {
        "total_requested": total_requested,
        "total_found": len(files),
        "missing": len(missing_files),
        "parse_errors": len(parse_errors),
        "repeated_subtypes": len(repeated),
        "out_txt": out_txt,
        # Datos ya estructurados (no solo el TXT), para que quien los
        # necesite (p.ej. el exportador a Excel) no tenga que reparsear
        # el texto plano.
        "repeated": repeated,
    }
    logger.info(
        "Verificacion finalizada: %s archivos analizados, %s subtipos repetidos encontrados",
        summary["total_found"], summary["repeated_subtypes"],
    )
    return summary


def _write_report(out_txt: Path, repeated, missing_files, parse_errors, total_requested, total_found) -> None:
    lines = [
        "SUBTIPOS REPETIDOS R3 / V3",
        "==========================",
        "",
        f"Archivos solicitados R3: {total_requested}",
        f"Archivos encontrados R3: {total_found}",
        f"Archivos faltantes R3: {len(missing_files)}",
        f"Errores de parseo: {len(parse_errors)}",
        f"Subtipos repetidos encontrados: {len(repeated)}",
        "",
    ]

    if missing_files:
        lines += ["ARCHIVOS FALTANTES", "------------------"]
        lines += [f"- {name}" for name in missing_files]
        lines.append("")

    if parse_errors:
        lines += ["ERRORES DE PARSEO", "-----------------"]
        lines += [f"- {e['archivo']}: {e['error']}" for e in parse_errors]
        lines.append("")

    if not repeated:
        lines.append("No se encontraron subtipos repetidos en R3.")
    else:
        lines += ["DETALLE", "-------", ""]
        for index, item in enumerate(repeated, start=1):
            lines.append(f"{index}. Subtipo: {item['subtipo']}")
            lines.append(f"   Cantidad de archivos: {len(item['archivos'])}")
            variantes = sorted(item["variantes"])
            if len(variantes) > 1:
                lines.append("   Variantes tipoDocumento:")
                lines += [f"   - {v}" for v in variantes]
            lines.append("   Archivos:")
            for info in item["archivos"]:
                lines.append(f"   - Archivo: {info['archivo']}")
                lines.append(f"     Proceso: {info['proceso']}")
            lines.append("")

    out_txt.write_text("\n".join(lines), encoding="utf-8")
