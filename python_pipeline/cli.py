"""
Punto de entrada unico del pipeline.

Antes: ejecutar_pipeline_dynamo.sh + 5 wrappers `N_paso.sh` que solo
reenviaban argumentos a un script real. Ahora: un CLI con subcomandos.

Ejemplos:
  python -m python_pipeline.cli                                    (menu interactivo)
  python -m python_pipeline.cli run-all --env qa
  python -m python_pipeline.cli descargar --env qa --tabla config-control
  python -m python_pipeline.cli comparar --r3-dir X --ta-dir Y --out-dir Z
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import compare, config, download, events_analysis, group_report, new_vs_baseline, verify_repeated
from .aws_client import CredentialsError, load_credentials_file
from .download import TableNotFoundError
from .pipeline_service import _find_default_reference_dir, ejecutar_pipeline_completo

logger = logging.getLogger("pipeline")


def _configure_logging(verbose: bool) -> None:
    # stdout (no el stderr por defecto de basicConfig): asi el orden con
    # los print() de las cabeceras de paso ("=== Paso N/7 ===") queda
    # siempre correcto, sin que la terminal intercale dos flujos distintos.
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    if not verbose:
        # boto3/botocore/urllib3 son muy verbosos en INFO ("Found
        # credentials in environment variables.", detalles HTTP, etc.);
        # eso no le sirve al usuario final, solo ensucia la pantalla.
        for noisy_logger in ("boto3", "botocore", "urllib3", "s3transfer"):
            logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def _abrir_excel(path: Path) -> None:
    """Abre el Excel con la aplicacion por defecto de Windows (normalmente
    Excel) al terminar el pipeline, para no tener que ir a buscarlo."""
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except AttributeError:
        logger.info("No se pudo abrir el Excel automaticamente en este sistema. Abrelo manualmente: %s", path)
    except OSError as exc:
        logger.warning("No se pudo abrir el Excel automaticamente (%s). Abrelo manualmente: %s", exc, path)


def cmd_descargar(args: argparse.Namespace) -> None:
    if args.credenciales_file:
        load_credentials_file(Path(args.credenciales_file))

    if args.tabla == "ambas":
        tablas = ["config-control", "text-analyzer"]
    elif args.tabla == "todas":
        tablas = list(config.TABLE_DEFS)
    else:
        tablas = [args.tabla]
    today = datetime.now().strftime(config.DATE_FORMAT)

    completo = args.modo_descarga == "completo"
    for tabla in tablas:
        reference_dir = None if completo else (Path(args.referencia) if args.referencia else _find_default_reference_dir(tabla, args.env, today))
        logger.info(
            "Descargando %s (%s, modo %s). Referencia: %s",
            tabla, args.env, args.modo_descarga, reference_dir or "N/A (primera descarga o modo completo)",
        )
        download.download(
            environment=args.env, table_key=tabla, reference_dir=reference_dir,
            segments=args.segmentos, profile=args.perfil,
            max_attempts=args.reintentos, dry_run=args.dry_run, completo=completo,
        )


def cmd_comparar(args: argparse.Namespace) -> None:
    compare.compare(Path(args.r3_dir), Path(args.ta_dir), Path(args.out_dir))


def cmd_verificar(args: argparse.Namespace) -> None:
    verify_repeated.verify_repeated(
        args.r3_dir, Path(args.out_txt),
        Path(args.lista) if args.lista else None,
    )


def cmd_agrupar(args: argparse.Namespace) -> None:
    group_report.generate(Path(args.r3_dir), Path(args.detalle_csv), Path(args.out_csv))


def cmd_identificar_eventos(args: argparse.Namespace) -> None:
    events_analysis.generate(Path(args.events_dir), Path(args.out_xlsx))


def cmd_validar_nuevos(args: argparse.Namespace) -> None:
    new_vs_baseline.generate(
        Path(args.r3_dir), Path(args.orden_file), Path(args.out_csv),
        Path(args.detalle_csv) if args.detalle_csv else None,
    )


def cmd_run_all(args: argparse.Namespace) -> None:
    """Delgado a proposito: toda la logica de los 6 pasos vive en
    pipeline_service.ejecutar_pipeline_completo (compartida con cualquier UI
    que integre este pipeline) -- aca solo se traduce args -> parametros,
    se imprime en vivo via `log=print`, y se decide que hacer al final
    (mostrar resumen, abrir los Excel) que es un detalle de terminal."""
    modo_descarga = getattr(args, "modo_descarga", "incremental")

    def log(mensaje: str) -> None:
        print()
        print(mensaje)

    try:
        resultado = ejecutar_pipeline_completo(
            environment=args.env, modo_descarga=modo_descarga,
            segments=args.segmentos, profile=args.perfil, max_attempts=args.reintentos,
            credenciales_file=Path(args.credenciales_file) if args.credenciales_file else None,
            log=log,
        )
    except (CredentialsError, TableNotFoundError) as exc:
        logger.error(str(exc))
        sys.exit(1)

    print()
    print("=" * 60)
    print("RESUMEN")
    print("=" * 60)
    for clave, valor in resultado.resumen.items():
        print(f"  {clave}: {valor}")
    if resultado.excel_path:
        print()
        print(f"  Reporte para revisar: {resultado.excel_path}")
    if resultado.maestro_path:
        print(f"  Maestro global del ambiente (acumulable): {resultado.maestro_path}")
    if resultado.matriz_path:
        print(f"  Matriz de ambientes (acumulable): {resultado.matriz_path}")
    if resultado.historial_path:
        print(f"  Historial completo (acumulable): {resultado.historial_path}")
    print("=" * 60)

    if not getattr(args, "no_abrir", False):
        if resultado.excel_path:
            _abrir_excel(resultado.excel_path)
        if resultado.maestro_path:
            _abrir_excel(resultado.maestro_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline", description="Pipeline Dynamo config-control / text-analyzer.")
    parser.add_argument("--verbose", action="store_true", help="Logging detallado (DEBUG).")
    sub = parser.add_subparsers(dest="comando", required=False)

    common_aws = argparse.ArgumentParser(add_help=False)
    common_aws.add_argument("--env", choices=config.ENVIRONMENTS, required=True, help="Ambiente.")
    common_aws.add_argument("--segmentos", type=int, default=None,
                             help="Segmentos paralelos de scan. Si se omite, se elige solo segun el tamano de la tabla.")
    common_aws.add_argument("--perfil", default=None, help="Perfil de AWS (~/.aws/credentials). Si se omite, usa variables de entorno.")
    common_aws.add_argument("--reintentos", type=int, default=download.DEFAULT_MAX_ATTEMPTS,
                             help=f"Reintentos maximos ante throttling de Dynamo (default {download.DEFAULT_MAX_ATTEMPTS}).")
    common_aws.add_argument("--credenciales-file", default=None,
                             help="Archivo con credenciales AWS (JSON o texto con 'export AWS_...='), "
                                  "para no pegarlas a mano en la terminal. Ver aws_credentials.json de ejemplo.")
    common_aws.add_argument(
        "--modo-descarga", choices=["incremental", "completo"], default="incremental",
        help="'incremental' (default): rapido, solo trae lo nuevo desde la ultima descarga. "
             "'completo': trae todo, ignora la descarga anterior (mas lento, pero necesario de vez en "
             "cuando para que el maestro pueda detectar flujos eliminados de verdad).",
    )

    p_descargar = sub.add_parser("descargar", parents=[common_aws], help="Descarga una tabla DynamoDB.")
    p_descargar.add_argument(
        "--tabla",
        choices=[*config.TABLE_DEFS, "ambas", "todas"],
        required=True,
        help="'ambas' = config-control + text-analyzer (para el flujo de comparacion). 'todas' = las 3 tablas.",
    )
    p_descargar.add_argument("--referencia", default=None, help="Carpeta de una descarga previa, para marcar que es nuevo (ignorado si --modo-descarga completo).")
    p_descargar.add_argument("--dry-run", action="store_true", help="Escanea y clasifica pero no escribe nada a disco.")
    p_descargar.set_defaults(func=cmd_descargar)

    p_comparar = sub.add_parser("comparar", help="Compara R3 (use_case) vs Text Analyzer (cu_name).")
    p_comparar.add_argument("--r3-dir", required=True)
    p_comparar.add_argument("--ta-dir", required=True)
    p_comparar.add_argument("--out-dir", required=True)
    p_comparar.set_defaults(func=cmd_comparar)

    p_verificar = sub.add_parser("verificar", help="Detecta subtipos R3 repetidos.")
    p_verificar.add_argument("--r3-dir", required=True)
    p_verificar.add_argument("--out-txt", required=True)
    p_verificar.add_argument("--lista", default=None, help="Archivo opcional con nombres de JSON a validar (uno por linea).")
    p_verificar.set_defaults(func=cmd_verificar)

    p_agrupar = sub.add_parser("agrupar", help="Reporte agrupado de subtipos.")
    p_agrupar.add_argument("--r3-dir", required=True)
    p_agrupar.add_argument("--detalle-csv", required=True)
    p_agrupar.add_argument("--out-csv", required=True)
    p_agrupar.set_defaults(func=cmd_agrupar)

    p_validar = sub.add_parser("validar-nuevos", help="Nuevos R3 vs Orden_RE_Base.txt.")
    p_validar.add_argument("--r3-dir", required=True)
    p_validar.add_argument("--orden-file", default=str(config.ORDEN_BASE_FILE))
    p_validar.add_argument("--out-csv", required=True)
    p_validar.add_argument("--detalle-csv", default=None)
    p_validar.set_defaults(func=cmd_validar_nuevos)

    p_run_all = sub.add_parser("run-all", parents=[common_aws], help="Corre el pipeline completo (los 6 pasos).")
    p_run_all.add_argument("--no-abrir", action="store_true", help="No abrir el Excel automaticamente al terminar.")
    p_run_all.set_defaults(func=cmd_run_all)

    p_eventos = sub.add_parser(
        "identificar-eventos",
        help="En events-manager (UDZ): identifica por flujo si tiene crudos, transmisiones o ambos.",
    )
    p_eventos.add_argument("--events-dir", required=True, help="Carpeta descargada de events-manager (crudos/ y resultados/).")
    p_eventos.add_argument("--out-xlsx", required=True)
    p_eventos.set_defaults(func=cmd_identificar_eventos)

    sub.add_parser("menu", help="Menu interactivo (tambien se activa si no das ningun comando).")

    return parser


def main(argv: Optional[list] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", False))

    # Un solo comando simple sin flags: `python -m python_pipeline.cli`
    # (o `aid-pipeline` si esta instalado) abre el menu interactivo en vez
    # de exigir memorizar subcomandos y flags.
    if args.comando is None or args.comando == "menu":
        from . import menu
        menu.run()
        return

    try:
        args.func(args)
    except (CredentialsError, TableNotFoundError, FileNotFoundError) as exc:
        logger.error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
