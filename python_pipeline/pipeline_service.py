"""
Pipeline completo (los 6 pasos) como funcion reusable, sin depender de
argparse ni de print() a stdout -- para que tanto el CLI (`cli.cmd_run_all`)
como una interfaz grafica (ver ui/inventario.py en el proyecto que integra
esto con "Despliegues AID") puedan correr exactamente la misma logica sin
duplicarla.

Extraido de cli.cmd_run_all tal cual estaba, cambiando solo `print()` por
llamadas a `log()` (por defecto no hace nada; el CLI le pasa `print`, una UI
le puede pasar algo que escriba en pantalla en vivo).

Nota: el paso original "comparar contra Orden_RE_Base.txt" (new_vs_baseline)
se sacó del flujo automático -- ese catálogo nunca se llegó a mantener, así
que siempre mostraba "No calculado". El módulo new_vs_baseline.py y el
subcomando `validar-nuevos` del CLI siguen disponibles para quien quiera
usarlos a mano si algún día arman ese catálogo.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import common, compare, config, download, events_analysis, excel_report, group_report, historial, matriz_ambientes, verify_repeated
from .aws_client import CredentialsError, load_credentials_file
from .download import DEFAULT_MAX_ATTEMPTS, TableNotFoundError

logger = logging.getLogger("pipeline")


@dataclass
class ResultadoPipeline:
    """Todo lo que produjo una corrida del pipeline completo, para que quien
    lo llamo (CLI o UI) decida que hacer (abrir los Excel, mostrar un
    resumen, etc.) sin tener que volver a leer nada del disco."""
    environment: str
    modo_descarga: str = "incremental"
    resumen: dict = field(default_factory=dict)
    excel_path: Optional[Path] = None
    maestro_path: Optional[Path] = None
    matriz_path: Optional[Path] = None
    historial_path: Optional[Path] = None


def _find_default_reference_dir(table_key: str, environment: str, today: str) -> Optional[Path]:
    """Igual que cli._find_default_reference_dir -- autodetecta la carpeta
    de fecha mas reciente ya descargada (distinta a hoy) para usarla como
    referencia en modo incremental."""
    import re

    date_iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    date_legacy_re = re.compile(r"^\d{8}$")

    def latest_subdir(base_dir: Path, pattern, exclude: str) -> Optional[Path]:
        if not base_dir.is_dir():
            return None
        candidates = sorted(
            p.name for p in base_dir.iterdir()
            if p.is_dir() and pattern.match(p.name) and p.name != exclude
        )
        return base_dir / candidates[-1] if candidates else None

    new_base = config.DESCARGAS_DIR / table_key / environment
    found = latest_subdir(new_base, date_iso_re, today)
    if found:
        return found

    legacy_folder = config.LEGACY_FOLDERS.get(table_key)
    if not legacy_folder:
        return None
    legacy_today = today.replace("-", "")
    legacy_base = config.BASE_DIR / legacy_folder / environment
    return latest_subdir(legacy_base, date_legacy_re, legacy_today)


def ejecutar_pipeline_completo(
    environment: str,
    modo_descarga: str = "incremental",
    segments: Optional[int] = None,
    profile: Optional[str] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    credenciales_file: Optional[Path] = None,
    log: Callable[[str], None] = lambda _msg: None,
) -> ResultadoPipeline:
    """Corre los 6 pasos del pipeline (descarga -> comparar -> verificar ->
    agrupar -> actualizar maestro/historial -> generar Excel) para un
    ambiente, y devuelve las rutas de los Excel generados en vez de abrirlos
    o imprimir un resumen -- eso lo decide quien llama.

    `log(mensaje)` se llama en cada paso importante; por defecto no hace
    nada (silencioso), el CLI le pasa `print`, una UI le puede pasar algo
    que actualice un log en pantalla en vivo."""
    if credenciales_file:
        load_credentials_file(Path(credenciales_file))

    now = datetime.now()
    date_stamp = now.strftime(config.DATE_FORMAT)
    report_root = config.REPORTES_DIR / environment / date_stamp
    report_root.mkdir(parents=True, exist_ok=True)
    run_tag = common.human_datetime(now)

    compare_output_dir = report_root / "comparacion"
    verify_out_txt = report_root / "subtipos_repetidos.txt"
    group_out_csv = report_root / "reporte_agrupado.csv"
    detalle_csv = compare_output_dir / "detalle_r3_vs_ta.csv"

    resultado = ResultadoPipeline(environment=environment, modo_descarga=modo_descarga)

    completo = modo_descarga == "completo"
    config_reference_dir = None if completo else _find_default_reference_dir("config-control", environment, date_stamp)
    ta_reference_dir = None if completo else _find_default_reference_dir("text-analyzer", environment, date_stamp)
    events_reference_dir = None if completo else _find_default_reference_dir("events-manager", environment, date_stamp)

    log(f"=== Paso 1/6: descargando config-control, text-analyzer y events-manager ({environment}, modo {modo_descarga}) ===")

    config_summary = download.download(environment, "config-control", config_reference_dir, segments, profile, date_stamp, max_attempts, completo=completo)
    download.download(environment, "text-analyzer", ta_reference_dir, segments, profile, date_stamp, max_attempts, completo=completo)

    # events-manager (UDZ) solo sirve para la columna "Transmisiones"; si
    # falla (tabla no existe en este ambiente, sin permiso, etc.) no debe
    # tumbar el resto del pipeline, solo esa columna queda vacia.
    resultados_basenames: Optional[set] = None
    try:
        download.download(environment, "events-manager", events_reference_dir, segments, profile, date_stamp, max_attempts, completo=completo)
        resultados_basenames = events_analysis.resultados_basenames(
            config.download_dir("events-manager", environment, date_stamp)
        )
    except (CredentialsError, TableNotFoundError) as exc:
        log(f"No se pudo descargar events-manager ({exc}); se omite la columna Transmisiones.")

    r3_dir = config.download_dir("config-control", environment, date_stamp) / "R3"
    r2_dir = config.download_dir("config-control", environment, date_stamp) / "R2"
    ta_dir = config.download_dir("text-analyzer", environment, date_stamp)
    r2_rows = group_report.list_flat(r2_dir)

    if not r3_dir.is_dir():
        log(f"No hay flujos R3 en la descarga ({r3_dir}); se omiten los pasos 2-6.")
        return resultado
    if not ta_dir.is_dir():
        log(f"No hay datos de Text Analyzer en la descarga ({ta_dir}); se omiten los pasos 2-6.")
        return resultado

    log("=== Paso 2/6: comparando R3 vs Text Analyzer ===")
    compare_summary = compare.compare(r3_dir, ta_dir, compare_output_dir)

    log("=== Paso 3/6: buscando subtipos de documento repetidos ===")
    verify_summary = verify_repeated.verify_repeated(str(r3_dir), verify_out_txt)

    log("=== Paso 4/6: agrupando el reporte por subtipo ===")
    total_r3, _suma, total_subtipos = group_report.generate(r3_dir, detalle_csv, group_out_csv, resultados_basenames)

    log(f"=== Paso 5/6: actualizando el maestro global del ambiente (modo {modo_descarga}) ===")
    filas_actuales = group_report.snapshot_rows(r3_dir, detalle_csv, resultados_basenames)
    historial_resumen = historial.actualizar(environment, filas_actuales, modo=modo_descarga)
    # Los R2 se acumulan en su propio namespace de historial (mismo módulo,
    # otra "carpeta de ambiente" — "<ambiente>__r2"), separado de los R3, así
    # no se pierden entre corridas como pasaba antes (solo vivían en el
    # reporte_completo.xlsx de esa corrida puntual).
    historial.actualizar(f"{environment}__r2", r2_rows, modo=modo_descarga)
    r2_maestro = historial.flujos_presentes(f"{environment}__r2")
    if any(historial_resumen.values()):
        log(
            f"  {len(historial_resumen['nuevos'])} nuevos, "
            f"{len(historial_resumen['cambios'])} con cambios, "
            f"{len(historial_resumen['eliminados'])} eliminados desde la ultima corrida."
        )
    else:
        log("  Sin cambios desde la ultima corrida.")

    historial_path = config.REPORTES_DIR / f"historial_{environment}.xlsx"
    try:
        excel_report.build_historial_workbook(historial_path, historial.eventos_completos(environment))
        resultado.historial_path = historial_path
    except RuntimeError as exc:
        log(f"No se genero el Excel de historial: {exc}")

    maestro_path = config.REPORTES_DIR / f"maestro_{environment}.xlsx"
    try:
        flujos_maestro = historial.flujos_presentes(environment)
        rows_maestro = group_report.group_rows(flujos_maestro)
        maestro_csv = report_root / "_maestro_tmp.csv"
        group_report.write_grouped_csv(rows_maestro, maestro_csv, incluir_transmisiones=True)
        excel_report.build_maestro_workbook(
            maestro_path, maestro_csv,
            resumen={
                "Ambiente": environment,
                "Actualizado": run_tag,
                "Total de flujos conocidos (presentes)": len(flujos_maestro),
                "Items R2 conocidos (presentes)": len(r2_maestro),
            },
            r2_rows=r2_maestro,
        )
        maestro_csv.unlink(missing_ok=True)
        resultado.maestro_path = maestro_path
    except RuntimeError as exc:
        log(f"No se genero el Excel maestro: {exc}")

    matriz_data = matriz_ambientes.actualizar(environment, filas_actuales, modo=modo_descarga)

    log("=== Paso 6/6: generando el Excel final ===")
    try:
        resumen = {
            "Ambiente": environment,
            "Fecha de la corrida": run_tag,
            "R3 analizados": compare_summary["total_r3"],
            "Coincidencias R3 con Text Analyzer": compare_summary["matched"],
            "R3 sin Text Analyzer (revisar)": compare_summary["unmatched"],
            "Subtipos de documento repetidos": verify_summary["repeated_subtypes"],
            "Subtipos distintos (reporte agrupado)": total_subtipos,
            "Flujos con Transmisiones": (
                len(resultados_basenames) if resultados_basenames is not None
                else "No calculado (fallo la descarga de events-manager)"
            ),
            "Nuevos vs corrida anterior": len(historial_resumen["nuevos"]),
            "Cambiaron vs corrida anterior": len(historial_resumen["cambios"]),
            "Eliminados vs corrida anterior": len(historial_resumen["eliminados"]),
            "Nombres repetidos en config-control": len(config_summary.nombres_repetidos),
            "Items en R2 (no procesados en el reporte agrupado)": len(r2_rows),
        }
        excel_path = report_root / "reporte_completo.xlsx"
        excel_report.build_workbook(
            excel_path, resumen=resumen,
            classified_file=compare_summary["classified_file"],
            unclassified_file=compare_summary["unclassified_file"],
            repeated=verify_summary["repeated"],
            group_csv=group_out_csv,
            historial_resumen=historial_resumen,
            r2_rows=r2_rows,
            nombres_repetidos=config_summary.nombres_repetidos,
        )
        resultado.excel_path = excel_path
        resultado.resumen = resumen

        matriz_path = config.REPORTES_DIR / "matriz_ambientes.xlsx"
        excel_report.build_matriz_workbook(matriz_path, matriz_data, environments=config.ENVIRONMENTS)
        resultado.matriz_path = matriz_path
    except RuntimeError as exc:
        log(f"No se genero el Excel: {exc}")

    if resultado.excel_path:
        # Ya todo quedo embebido en el Excel; no dejamos los CSV/TXT
        # intermedios sueltos en la carpeta de reportes.
        shutil.rmtree(compare_output_dir, ignore_errors=True)
        for leftover in (group_out_csv, verify_out_txt):
            leftover.unlink(missing_ok=True)

    return resultado
