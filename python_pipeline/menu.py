"""
Menu interactivo: para no tener que recordar flags, corres UN solo
comando (`python -m python_pipeline.cli`, sin argumentos, o `aid-pipeline`
si lo instalaste) y el programa te pregunta paso a paso que hacer.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from . import compare, config, download, events_analysis, group_report, new_vs_baseline, verify_repeated
from .aws_client import CredentialsError, load_credentials_file
from .cli import _configure_logging, _find_default_reference_dir, cmd_run_all
from .download import TableNotFoundError

logger = logging.getLogger("pipeline")


def _ask(prompt: str, default: Optional[str] = None, required: bool = True) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if not value and default is not None:
            return default
        if not value and not required:
            return ""
        if value:
            return value
        print("  -> Este dato es obligatorio.")


def _ask_choice(prompt: str, options: list[str], default: Optional[str] = None) -> str:
    print(f"{prompt}")
    for i, opt in enumerate(options, start=1):
        marker = " (default)" if opt == default else ""
        print(f"  {i}) {opt}{marker}")
    while True:
        raw = input("Elige numero u opcion: ").strip()
        if not raw and default:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw in options:
            return raw
        print("  -> Opcion invalida, intenta de nuevo.")


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    default_label = "S/n" if default else "s/N"
    raw = input(f"{prompt} [{default_label}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("s", "si", "y", "yes")


def _find_latest_download(table_key: str) -> Optional[Path]:
    """Busca la descarga mas reciente de una tabla, en cualquier ambiente,
    para no obligar al usuario a escribir la ruta completa cada vez que
    quiere repetir un paso individual (comparar/verificar/agrupar/etc.)."""
    base = config.DESCARGAS_DIR / table_key
    if not base.is_dir():
        return None
    candidates = [
        date_dir
        for env_dir in base.iterdir() if env_dir.is_dir()
        for date_dir in env_dir.iterdir() if date_dir.is_dir()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _resolve_credenciales() -> Optional[str]:
    default_file = config.BASE_DIR / "aws_credentials.json"
    if default_file.exists():
        if _ask_yes_no(f"Encontre {default_file.name}, usarlo para autenticar?", default=True):
            return str(default_file)
    raw = _ask("Ruta a archivo de credenciales (vacio = usar variables de entorno / --perfil)", default="", required=False)
    return raw or None


class _Args:
    """Objeto simple que imita el Namespace de argparse, para reusar
    cmd_run_all() sin duplicar su logica."""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _menu_modo_descarga() -> str:
    return _ask_choice(
        "Descargar todo o solo lo nuevo?",
        ["incremental (rapido, solo lo nuevo)", "completo (todo, mas lento)"],
        default="incremental (rapido, solo lo nuevo)",
    ).split(" ", 1)[0]


def _menu_descargar() -> None:
    env = _ask_choice("Que ambiente?", list(config.ENVIRONMENTS), default="qa")
    tabla = _ask_choice("Que tabla?", [*config.TABLE_DEFS, "ambas", "todas"], default="ambas")
    modo = _menu_modo_descarga()
    cred_file = _resolve_credenciales()
    if cred_file:
        load_credentials_file(Path(cred_file))

    dry_run = _ask_yes_no("Modo dry-run (no escribe nada, solo previsualiza)?", default=False)

    tablas = ["config-control", "text-analyzer"] if tabla == "ambas" else (list(config.TABLE_DEFS) if tabla == "todas" else [tabla])
    from datetime import datetime
    today = datetime.now().strftime(config.DATE_FORMAT)
    completo = modo == "completo"

    for t in tablas:
        reference_dir = None if completo else _find_default_reference_dir(t, env, today)
        print(f"\nDescargando '{t}' ({env}, modo {modo}). Referencia: {reference_dir or 'N/A'}")
        download.download(
            environment=env, table_key=t, reference_dir=reference_dir,
            dry_run=dry_run, completo=completo,
        )


def _menu_run_all() -> None:
    env = _ask_choice("Que ambiente?", list(config.ENVIRONMENTS), default="qa")
    modo = _menu_modo_descarga()
    cred_file = _resolve_credenciales()

    args = _Args(
        env=env, perfil=None, segmentos=None, reintentos=download.DEFAULT_MAX_ATTEMPTS,
        credenciales_file=cred_file, modo_descarga=modo,
    )
    cmd_run_all(args)


def _menu_comparar() -> None:
    r3_default = _find_latest_download("config-control")
    ta_default = _find_latest_download("text-analyzer")
    r3_dir = _ask("Carpeta R3", default=str(r3_default / "R3") if r3_default else None)
    ta_dir = _ask("Carpeta Text Analyzer", default=str(ta_default) if ta_default else None)
    out_dir = _ask("Carpeta de salida", default="coincidencia")
    compare.compare(Path(r3_dir), Path(ta_dir), Path(out_dir))


def _menu_verificar() -> None:
    r3_default = _find_latest_download("config-control")
    r3_dir = _ask(
        "Carpeta R3 (o carpeta.zip/subcarpeta)",
        default=str(r3_default / "R3") if r3_default else None,
    )
    out_txt = _ask("Archivo TXT de salida", default="subtipos_repetidos.txt")
    lista = _ask("Archivo con lista de JSON a validar (vacio = todos)", default="", required=False)
    verify_repeated.verify_repeated(r3_dir, Path(out_txt), Path(lista) if lista else None)


def _menu_agrupar() -> None:
    r3_default = _find_latest_download("config-control")
    r3_dir = _ask("Carpeta R3", default=str(r3_default / "R3") if r3_default else None)
    detalle_csv = _ask("CSV de detalle (salida del paso Comparar)")
    out_csv = _ask("CSV de salida", default="reporte_subtipos_agrupado.csv")
    group_report.generate(Path(r3_dir), Path(detalle_csv), Path(out_csv))


def _menu_validar_nuevos() -> None:
    r3_default = _find_latest_download("config-control")
    r3_dir = _ask("Carpeta R3", default=str(r3_default / "R3") if r3_default else None)
    orden_file = _ask("Archivo Orden_RE_Base.txt", default=str(config.ORDEN_BASE_FILE))
    out_csv = _ask("CSV de salida", default="nuevos_items_R3.csv")
    detalle_csv = _ask("CSV de detalle (opcional)", default="", required=False)
    new_vs_baseline.generate(Path(r3_dir), Path(orden_file), Path(out_csv), Path(detalle_csv) if detalle_csv else None)


def _menu_identificar_eventos() -> None:
    events_default = _find_latest_download("events-manager")
    events_dir = _ask(
        "Carpeta descargada de events-manager (UDZ)",
        default=str(events_default) if events_default else None,
    )
    out_xlsx = _ask("Excel de salida", default="identificacion_eventos.xlsx")
    events_analysis.generate(Path(events_dir), Path(out_xlsx))


_MENU_ACTIONS = {
    "1": ("Descargar una tabla", _menu_descargar),
    "2": ("Ejecutar pipeline completo (descarga + analisis + Excel final)", _menu_run_all),
    "3": ("Comparar R3 vs Text Analyzer", _menu_comparar),
    "4": ("Verificar subtipos repetidos", _menu_verificar),
    "5": ("Agrupar reporte por subtipos", _menu_agrupar),
    "6": ("Validar nuevos R3 vs Orden_RE_Base.txt", _menu_validar_nuevos),
    "7": ("Identificar eventos UDZ (crudos / transmisiones)", _menu_identificar_eventos),
}


def run() -> None:
    _configure_logging(verbose=False)
    print("=" * 60)
    print("PIPELINE DYNAMO - config-control / text-analyzer")
    print("=" * 60)

    while True:
        print("\nQue quieres hacer?")
        for key, (label, _fn) in _MENU_ACTIONS.items():
            print(f"  {key}) {label}")
        print("  0) Salir")

        choice = input("\nOpcion: ").strip()
        if choice == "0":
            print("Listo, hasta luego.")
            return

        action = _MENU_ACTIONS.get(choice)
        if not action:
            print("Opcion invalida.")
            continue

        _label, fn = action
        try:
            fn()
        except (CredentialsError, TableNotFoundError, FileNotFoundError) as exc:
            print(f"\nError: {exc}")
        except KeyboardInterrupt:
            print("\nCancelado.")
        except Exception as exc:  # ultima defensa: que el menu nunca se caiga
            logger.exception("Fallo inesperado")
            print(f"\nError inesperado: {exc}")
