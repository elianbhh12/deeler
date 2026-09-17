"""
Paso 4: reporte agrupado de subtipos, una fila por JSON. El nombre del
subtipo y la cantidad solo se muestran en la primera fila de cada grupo
(igual formato que generar_reporte_subtipos_agrupado.py). El orden fijo
de archivos ahora viene de referencias/pipeline_config.json en vez de
estar escrito dentro del codigo.

`group_rows` y `write_grouped_csv` estan separados de `generate` (que
arma las filas leyendo un R3 recien descargado) para poder reusar
exactamente la misma logica de agrupar/ordenar/escribir con filas que
vienen de otro lado (el maestro acumulado por ambiente, en maestro.py).
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import common, config

logger = logging.getLogger(__name__)

_ORDER_INDEX = {name: i for i, name in enumerate(config.ORDEN_REPORTE_SUBTIPOS)}

# Como quedan clasificados los R3 al descargarse (download.py los separa
# en subcarpetas topics/ms segun si algun paso del flujo es tipo "topic").
_TIPO_LABELS = {"topics": "R3 - Topics", "ms": "R3 - MS"}

CSV_HEADER_BASE = ["Nombre de los JSONs", "Nombre TA config", "Nombre del subtipo",
                    "Cantidad de archivos con ese subtipo", "Proceso", "Ruta JSON R3", "Observaciones"]


def _order_key(file_name: str) -> Tuple[int, int, str]:
    if file_name in _ORDER_INDEX:
        return (0, _ORDER_INDEX[file_name], file_name)
    return (1, len(config.ORDEN_REPORTE_SUBTIPOS), common.normalize_text(file_name))


def _load_detalle(detalle_csv: Path) -> List[dict]:
    rows = []
    with detalle_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            if (row.get("Nombre de los JSONs") or "").strip():
                rows.append(row)
    return rows


def _load_r3_info(r3_dir: Path) -> Dict[str, dict]:
    info = {}
    for json_file, data in common.load_json_files(r3_dir):
        # download.py guarda cada item en R3/topics o R3/ms segun su
        # clasificacion; ese primer segmento de carpeta, relativo a r3_dir,
        # es el "tipo" (se perdia apenas se armaba este reporte).
        partes = json_file.relative_to(r3_dir).parts
        tipo_carpeta = partes[0] if len(partes) > 1 else ""
        info[json_file.name] = {
            "subtipo": common.get_tipo_documento(data),
            "proceso": common.get_proceso(data),
            "s3_path": str(data.get("s3_path") or ""),
            "tipo": _TIPO_LABELS.get(tipo_carpeta, tipo_carpeta),
        }
    return info


def group_rows(rows: List[dict]) -> List[dict]:
    """Toma filas planas (cada una con al menos 'file' y 'subtipo') y las
    agrupa/ordena para presentacion tipo Reporte Agrupado: agrega
    'subtipo_grupo', 'count_grupo' y 'norm_grupo', garantizando que cada
    grupo quede contiguo (ver nota mas abajo sobre por que importa)."""
    grupos: Dict[str, dict] = {}
    for row in rows:
        subtipo = row.get("subtipo") or "REVISAR_MANUAL"
        norm = common.normalize_text(subtipo) or "revisar manual"
        grupo = grupos.setdefault(norm, {"subtipo": subtipo, "rows": []})
        row = dict(row)
        row["order_key"] = _order_key(row["file"])
        grupo["rows"].append(row)

    # IMPORTANTE: hay que ordenar por GRUPO primero (no por archivo suelto),
    # o filas del mismo subtipo pueden quedar no-contiguas cuando alguno de
    # sus archivos no esta en la lista curada de ORDEN_REPORTE_SUBTIPOS (se
    # ordena alfabeticamente por su cuenta, ignorando a que subtipo pertenece).
    # Si eso pasa, el subtipo/cantidad que se "oculta" en las filas repetidas
    # del grupo termina pareciendo el de otro grupo distinto en el Excel
    # (fusion de celdas y subtipos que se ven trocados/cambiados de lugar).
    for grupo in grupos.values():
        grupo["rows"].sort(key=lambda r: (r["order_key"], common.normalize_text(r["file"])))
        grupo["group_order_key"] = min(r["order_key"] for r in grupo["rows"])

    grupos_ordenados = sorted(
        grupos.items(),
        key=lambda kv: (kv[1]["group_order_key"], common.normalize_text(kv[1]["subtipo"])),
    )

    salida: List[dict] = []
    for norm, grupo in grupos_ordenados:
        for row in grupo["rows"]:
            row = dict(row)
            row["subtipo_grupo"] = grupo["subtipo"]
            row["count_grupo"] = len(grupo["rows"])
            row["norm_grupo"] = norm
            salida.append(row)
    return salida


def write_grouped_csv(rows: List[dict], out_csv: Path, incluir_transmisiones: bool) -> Tuple[int, int, int]:
    """rows: salida de group_rows(). Escribe el CSV con el formato
    'agrupado visual' (subtipo/cantidad solo en la primera fila de cada
    grupo) + columna Tipo al final + fila TOTAL_R3."""
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    grupos_impresos = set()
    grupos_vistos: Dict[str, int] = {}

    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";", lineterminator="\n")
        header = list(CSV_HEADER_BASE)
        if incluir_transmisiones:
            header.append("Transmisiones")
        header.append("Tipo")
        writer.writerow(header)

        for row in rows:
            mostrar = row["norm_grupo"] not in grupos_impresos
            fila = [
                row["file"], row.get("ta_config", ""),
                row["subtipo_grupo"] if mostrar else "",
                row["count_grupo"] if mostrar else "",
                row.get("proceso", ""), row.get("s3_path", ""), row.get("observacion", ""),
            ]
            if incluir_transmisiones:
                fila.append(row.get("transmisiones", ""))
            fila.append(row.get("tipo", ""))
            writer.writerow(fila)
            grupos_impresos.add(row["norm_grupo"])
            grupos_vistos[row["norm_grupo"]] = grupos_vistos.get(row["norm_grupo"], 0) + 1
            total += 1

        writer.writerow([])
        total_row = ["TOTAL_R3", "", "", total, "", "", ""]
        if incluir_transmisiones:
            total_row.append("")
        total_row.append("")
        writer.writerow(total_row)

    suma_grupos = sum(grupos_vistos.values())
    if total != suma_grupos:
        raise RuntimeError("La suma de grupos no coincide con el total de filas")

    return total, suma_grupos, len(grupos_vistos)


def _flat_rows(r3_dir: Path, detalle_csv: Path, resultados_basenames: Optional[set]) -> List[dict]:
    """Una fila plana por archivo R3 (sin agrupar todavia), con todos los
    campos del Reporte Agrupado: file, ta_config, subtipo, proceso,
    s3_path, observacion, tipo, y transmisiones si se paso el cruce."""
    detalle_rows = _load_detalle(detalle_csv)
    r3_info = _load_r3_info(r3_dir)

    filas: List[dict] = []
    for detalle_row in detalle_rows:
        file_name = (detalle_row.get("Nombre de los JSONs") or "").strip()
        info = r3_info.get(file_name, {})
        subtipo = (detalle_row.get("Nombre del subtipo") or "").strip() or info.get("subtipo") or "REVISAR_MANUAL"

        fila = {
            "file": file_name,
            "ta_config": (detalle_row.get("Nombre TA config") or "").strip(),
            "subtipo": subtipo,
            "proceso": info.get("proceso", ""),
            "s3_path": (detalle_row.get("Ruta JSON R3") or "").strip() or info.get("s3_path", ""),
            "observacion": (detalle_row.get("Observaciones") or "").strip(),
            "tipo": info.get("tipo", ""),
        }
        if resultados_basenames is not None:
            fila["transmisiones"] = "Si" if Path(file_name).stem in resultados_basenames else "No"
        filas.append(fila)

    return filas


def list_flat(directory: Path) -> List[dict]:
    """Listado simple (sin agrupar por subtipo) de los JSON en una carpeta.
    Para carpetas que no pasan por el flujo completo de comparacion contra
    Text Analyzer (p.ej. R2), asi quedan visibles en el Excel en vez de
    perderse silenciosamente."""
    if not directory.is_dir():
        return []
    rows = [
        {
            "file": json_file.name,
            "subtipo": common.get_tipo_documento(data),
            "proceso": common.get_proceso(data),
            "s3_path": str(data.get("s3_path") or ""),
        }
        for json_file, data in common.load_json_files(directory)
    ]
    return sorted(rows, key=lambda r: common.normalize_text(r["file"]))


def snapshot_rows(r3_dir: Path, detalle_csv: Path, resultados_basenames: Optional[set] = None) -> List[dict]:
    """Una fila plana por flujo con su estado actual completo (los mismos
    campos del Reporte Agrupado). La usan historial.py/maestro.py para
    comparar una corrida contra el estado acumulado del ambiente."""
    return _flat_rows(r3_dir, detalle_csv, resultados_basenames)


def generate(
    r3_dir: Path, detalle_csv: Path, out_csv: Path,
    resultados_basenames: Optional[set] = None,
) -> Tuple[int, int, int]:
    """resultados_basenames: si se pasa (set de nombres de flujo, del
    cruce con events-manager), agrega una columna 'Transmisiones' (Si/No)
    por archivo. Si se omite, el reporte queda igual que antes."""
    flat = _flat_rows(r3_dir, detalle_csv, resultados_basenames)
    rows = group_rows(flat)
    total, suma, subtipos = write_grouped_csv(rows, out_csv, incluir_transmisiones=resultados_basenames is not None)
    logger.info("Reporte agrupado generado: %s (R3=%s, subtipos=%s)", out_csv, total, subtipos)
    return total, suma, subtipos
