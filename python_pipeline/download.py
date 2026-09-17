"""
Paso 1: descarga de una tabla DynamoDB y clasificacion en carpetas
R2 / R3/topics / R3/ms / R3_Nuevos / use_case / use_case_TA.

Diferencias frente a download_from_dynamo.sh:
  - boto3 en vez de `aws dynamodb scan` + jq: sin parseo de texto, sin
    subprocesos por pagina; el "unmarshal" de tipos Dynamo lo hace
    TypeDeserializer en una linea en vez de un filtro jq de 15 lineas.
  - STREAMING: cada item se clasifica y se escribe a disco apenas llega,
    en vez de acumular toda la tabla en memoria antes de guardar (el bash
    original tampoco acumulaba en RAM, pero la primera version de este
    modulo si lo hacia; para tablas grandes eso es un problema real de
    memoria que aqui se corrige).
  - Progreso real: se reporta el total acumulado de items guardados a
    medida que avanza el scan, no solo al terminar.
  - Reintentos configurables: usa botocore Config(retries={"mode":
    "adaptive"}) para absorber throttling de DynamoDB en vez de fallar.
  - Valida que la tabla exista ANTES de lanzar el scan (evita que un
    ambiente/tabla mal escrito falle a mitad del scan paralelo).
  - Modo --dry-run: hace el scan y clasifica, pero no escribe nada a
    disco; sirve para previsualizar cuantos items nuevos habria.
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional

from . import common, config
from .aws_client import build_session, validate_credentials

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 8
PROGRESS_LOG_EVERY = 200  # items


class TableNotFoundError(RuntimeError):
    pass


def _get_deserializer():
    # Import perezoso (ver aws_client._import_boto3): permite que el resto
    # del paquete se importe sin tener boto3 instalado.
    from boto3.dynamodb.types import TypeDeserializer
    return TypeDeserializer()


def _build_client(session, max_attempts: int):
    from botocore.config import Config

    from .aws_client import VERIFY_TLS
    boto_config = Config(retries={"max_attempts": max_attempts, "mode": "adaptive"})
    return session.client("dynamodb", config=boto_config, verify=VERIFY_TLS)


def _deserialize_item(raw_item: dict, deserializer) -> dict:
    return {k: deserializer.deserialize(v) for k, v in raw_item.items()}


def _json_default(obj):
    # TypeDeserializer convierte los numeros ("N") de Dynamo en Decimal,
    # que json.dumps no sabe serializar por defecto.
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


@dataclass
class DownloadSummary:
    output_dir: Path
    dry_run: bool = False
    total_saved: int = 0
    total_existentes_referencia: int = 0
    counts_by_folder: Dict[str, int] = field(default_factory=dict)
    # nombre_base -> lista de {"archivo", "s3_path"} de los items que
    # terminaron compartiendo ese mismo nombre (solo grupos con 2+).
    nombres_repetidos: Dict[str, list] = field(default_factory=dict)


def _build_reference_keys(reference_dir: Optional[Path], field_name: str) -> set:
    if not reference_dir:
        return set()
    if not reference_dir.exists():
        raise FileNotFoundError(f"La ruta de inventario de referencia no existe: {reference_dir}")

    keys = set()
    for _json_file, data in common.load_json_files(reference_dir):
        value = data.get(field_name)
        if value:
            keys.add(str(value))
    return keys


def _classify_item(table_key: str, item: dict, fallback_index: int) -> tuple[str, str]:
    """Devuelve (flow_folder, safe_name), replicando la logica de
    download_from_dynamo.sh."""
    if table_key == "text-analyzer":
        cu_name = str(item.get("cu_name") or "")
        safe_name = common.sanitize_filename(cu_name) or f"item_{fallback_index}"
        flow_folder = "use_case" if common.has_nested_key(item, "use_case") else "use_case_TA"
        return flow_folder, safe_name

    if table_key == "events-manager":
        s3_path = str(item.get("s3_path") or "")
        tipo = common.classify_udz_tipo(s3_path) or "otros"
        last_segment = s3_path.rstrip("/").rsplit("/", 1)[-1]
        safe_name = common.sanitize_filename(last_segment) or f"item_{fallback_index}"
        return tipo, safe_name

    s3_path = str(item.get("s3_path") or "")
    if not s3_path:
        return "R3_Nuevos", f"item_{fallback_index}"

    normalized = s3_path.rstrip("/")
    last_segment = normalized.rsplit("/", 1)[-1]
    safe_name = common.sanitize_filename(last_segment) or f"item_{fallback_index}"

    if "r2-raw" in s3_path or "s3-raw" in s3_path:
        flow_folder = "R2"
    elif "udz" in s3_path:
        flow_folder = "R3/topics" if common.has_topic_step(item) else "R3/ms"
    else:
        flow_folder = "R3_Nuevos"
    return flow_folder, safe_name


class _ScanState:
    """Estado compartido entre los hilos de los distintos segmentos del
    scan paralelo. Todo lo que toca `used_names`/contadores/archivos pasa
    por `lock` para que dos segmentos no pisen el mismo nombre de archivo
    ni corrompan los contadores."""

    def __init__(self, table_key: str, output_base_dir: Path, reference_dir: Optional[Path],
                 reference_field: str, existing_keys: set, dry_run: bool, completo: bool = False):
        self.table_key = table_key
        self.output_base_dir = output_base_dir
        self.reference_dir = reference_dir
        self.reference_field = reference_field
        self.existing_keys = existing_keys
        self.dry_run = dry_run
        # completo=False (default): modo incremental, NO vuelve a escribir
        # los items que ya estaban en la referencia (rapido, poco disco).
        # La "verdad global" de cada ambiente no depende de esto -- vive en
        # el maestro acumulado (ver maestro.py), que se actualiza con lo
        # que se descargue cada vez, sea completo o no.
        # completo=True: ignora la referencia para decidir que escribir,
        # siempre guarda todo lo que hay en la tabla hoy.
        self.completo = completo

        self.lock = threading.Lock()
        self.used_names: Dict[str, bool] = {}
        self.counts_by_folder: Dict[str, int] = {}
        self.total_saved = 0
        self.total_existentes_referencia = 0
        self.total_seen = 0
        self.report_lines: list[str] = []
        # Agrupa por el nombre "base" (antes de renombrar por colision).
        # Al terminar el scan, cualquier grupo con mas de 1 elemento es un
        # nombre repetido: varios items de Dynamo que terminan en el mismo
        # s3_path, distinguidos solo por una carpeta intermedia distinta.
        self.by_base_name: Dict[str, list] = {}

    def process_item(self, item: dict) -> None:
        with self.lock:
            self.total_seen += 1
            flow_folder, safe_name = _classify_item(self.table_key, item, self.total_saved)

            # En modo incremental (completo=False, default), un item ya
            # conocido de la referencia NO se vuelve a escribir hoy -- eso
            # es lo que hace rapida la descarga de todos los dias. La
            # carpeta de hoy entonces solo representa "lo nuevo desde la
            # ultima vez", no la tabla completa; por eso el reporte de esa
            # corrida y el maestro acumulado (maestro.py) son cosas
            # distintas: el maestro es el que sabe la verdad completa.
            reference_key = str(item.get(self.reference_field) or "")
            if self.reference_dir and reference_key and reference_key in self.existing_keys:
                self.total_existentes_referencia += 1
                if not self.completo:
                    return

            output_dir = self.output_base_dir / flow_folder
            file_path = output_dir / f"{safe_name}.json"
            s3_path = str(item.get("s3_path") or "")

            if self.used_names.get(safe_name):
                if s3_path:
                    remainder = s3_path.removeprefix("s3://").split("/", 1)
                    suffix = remainder[1] if len(remainder) > 1 else remainder[0]
                    file_path = output_dir / f"{common.sanitize_filename(suffix)}.json"

            self.by_base_name.setdefault(safe_name, []).append({
                "archivo": file_path.name, "s3_path": s3_path,
            })

            if not self.dry_run:
                output_dir.mkdir(parents=True, exist_ok=True)
                file_path.write_text(
                    json.dumps(item, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8"
                )

            self.used_names[safe_name] = True
            self.total_saved += 1
            self.counts_by_folder[flow_folder] = self.counts_by_folder.get(flow_folder, 0) + 1

            if self.reference_dir and reference_key not in self.existing_keys:
                self.report_lines.append(f"{flow_folder};{safe_name};{s3_path};{file_path}")

            if self.total_saved % PROGRESS_LOG_EVERY == 0:
                logger.info("Progreso: %s items guardados hasta ahora...", self.total_saved)


def _scan_segment_stream(client, table_name: str, segment: int, total_segments: int,
                          state: _ScanState, deserializer) -> None:
    paginator = client.get_paginator("scan")
    page_kwargs = dict(TableName=table_name)
    if total_segments > 1:
        page_kwargs.update(Segment=segment, TotalSegments=total_segments)

    page_number = 0
    for page in paginator.paginate(**page_kwargs):
        page_number += 1
        raw_items = page.get("Items", [])
        for raw_item in raw_items:
            state.process_item(_deserialize_item(raw_item, deserializer))
        logger.info("Segmento %s: pagina %s (items en pagina: %s)", segment, page_number, len(raw_items))


def _check_table_exists(client, table_name: str):
    from botocore.exceptions import ClientError, EndpointConnectionError
    try:
        table = client.describe_table(TableName=table_name)["Table"]
        return table.get("ItemCount", "N/D")
    except EndpointConnectionError as exc:
        raise TableNotFoundError(
            f"No se pudo conectar a DynamoDB (¿estas en la red del banco?): {exc}"
        ) from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ResourceNotFoundException":
            raise TableNotFoundError(
                f"La tabla '{table_name}' no existe en esta cuenta/region. "
                "Revisa el ambiente (qa/pdn/dev) y tus credenciales."
            ) from exc
        logger.warning("No se pudo confirmar el conteo de items de la tabla (%s); se continua igual.", exc)
        return "N/D"


def _auto_segment_count(item_count) -> int:
    """Elige cuantos segmentos paralelos usar segun el tamano aproximado
    de la tabla, para que el usuario no tenga que adivinar un numero.
    Mas segmentos = mas rapido, pero tambien mas riesgo de throttling en
    tablas con poca capacidad, asi que se sube con moderacion."""
    if not isinstance(item_count, int):
        return 1
    if item_count <= 500:
        return 1
    if item_count <= 5_000:
        return 2
    if item_count <= 50_000:
        return 4
    return 8


def _write_manifest(
    output_base_dir: Path, environment: str, table_key: str, table_name: str,
    identity: dict, reference_dir: Optional[Path], item_count, summary: "DownloadSummary",
) -> None:
    """Deja un manifest.json con quien/cuando/que se descargo, para poder
    auditar una corrida sin tener que abrir los JSON uno por uno."""
    now = datetime.now()
    manifest = {
        "fecha_hora": now.isoformat(timespec="seconds"),
        "fecha_legible": common.human_datetime(now),
        "ambiente": environment,
        "tabla": table_key,
        "tabla_dynamo": table_name,
        "cuenta_aws": identity.get("Account"),
        "usuario_arn": identity.get("Arn"),
        "referencia_usada": str(reference_dir) if reference_dir else None,
        "items_en_tabla_aprox": item_count,
        "items_guardados": summary.total_saved,
        "items_ya_en_referencia": summary.total_existentes_referencia,
        "conteo_por_carpeta": summary.counts_by_folder,
        "nombres_repetidos_detectados": len(summary.nombres_repetidos),
    }
    (output_base_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def download(
    environment: str,
    table_key: str,
    reference_dir: Optional[Path] = None,
    segments: Optional[int] = None,
    profile: Optional[str] = None,
    date_stamp: Optional[str] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    dry_run: bool = False,
    completo: bool = False,
) -> DownloadSummary:
    table_name = config.resolve_table_name(table_key, environment)
    date_stamp = date_stamp or date.today().strftime(config.DATE_FORMAT)
    output_base_dir = config.download_dir(table_key, environment, date_stamp)
    if not dry_run:
        output_base_dir.mkdir(parents=True, exist_ok=True)

    session = build_session(profile=profile)
    identity = validate_credentials(session)
    client = _build_client(session, max_attempts)

    item_count = _check_table_exists(client, table_name)
    if segments is None:
        segments = _auto_segment_count(item_count)
        logger.info(
            "Segmentos paralelos elegidos automaticamente: %s (segun tamano de la tabla)", segments
        )
    logger.info("Tabla DynamoDB: %s (items aprox: %s)%s", table_name, item_count, " [DRY-RUN]" if dry_run else "")

    reference_field = "cu_name" if table_key == "text-analyzer" else "s3_path"
    existing_keys = _build_reference_keys(reference_dir, reference_field)
    if reference_dir:
        logger.info("Identificadores unicos en referencia (%s): %s", reference_field, len(existing_keys))

    state = _ScanState(table_key, output_base_dir, reference_dir, reference_field, existing_keys, dry_run, completo)
    deserializer = _get_deserializer()

    if segments <= 1:
        _scan_segment_stream(client, table_name, 0, 1, state, deserializer)
    else:
        with ThreadPoolExecutor(max_workers=segments) as pool:
            futures = [
                pool.submit(_scan_segment_stream, client, table_name, seg, segments, state, deserializer)
                for seg in range(segments)
            ]
            for future in futures:
                future.result()  # relanza cualquier excepcion ocurrida en un hilo

    if reference_dir and not dry_run:
        (output_base_dir / "nuevos_vs_referencia.txt").write_text(
            "\n".join(state.report_lines), encoding="utf-8"
        )

    nombres_repetidos = {name: items for name, items in state.by_base_name.items() if len(items) > 1}

    summary = DownloadSummary(
        output_dir=output_base_dir,
        dry_run=dry_run,
        total_saved=state.total_saved,
        total_existentes_referencia=state.total_existentes_referencia,
        counts_by_folder=state.counts_by_folder,
        nombres_repetidos=nombres_repetidos,
    )

    if not dry_run:
        _write_manifest(
            output_base_dir, environment, table_key, table_name, identity,
            reference_dir, item_count, summary,
        )

    if completo:
        logger.info(
            "Descarga completa finalizada%s. Total guardados hoy=%s (de esos, %s ya existian desde antes; %s son nuevos)",
            " (DRY-RUN, nada se escribio a disco)" if dry_run else "",
            summary.total_saved, summary.total_existentes_referencia,
            summary.total_saved - summary.total_existentes_referencia,
        )
    else:
        logger.info(
            "Descarga incremental finalizada%s. Nuevos guardados hoy=%s. Ya conocidos (no se volvieron a escribir)=%s",
            " (DRY-RUN, nada se escribio a disco)" if dry_run else "",
            summary.total_saved, summary.total_existentes_referencia,
        )
    for folder, count in summary.counts_by_folder.items():
        logger.info("  %s: %s", folder, count)
    if nombres_repetidos:
        total_afectados = sum(len(items) for items in nombres_repetidos.values())
        logger.warning(
            "%s nombres repetidos detectados (%s archivos afectados en total) -> %s",
            len(nombres_repetidos), total_afectados, output_base_dir / "nombres_repetidos.csv",
        )

    return summary
