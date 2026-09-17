"""
Configuracion del pipeline. Todo lo que antes estaba escrito a mano dentro
de la logica (nombres de tabla, observaciones manuales, orden del reporte)
vive ahora en referencias/pipeline_config.json, para poder editarlo sin
tocar codigo.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List

from . import sharepoint_source

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent  # .../flujosscript
REFERENCIAS_DIR = BASE_DIR / "referencias"
PIPELINE_CONFIG_FILE = REFERENCIAS_DIR / "pipeline_config.json"
ORDEN_BASE_FILE = REFERENCIAS_DIR / "Orden_RE_Base.txt"
# Conexion opcional al Excel maestro (SharePoint/OneDrive). Ver
# sharepoint_source.py para el detalle de como se configura y funciona.
SHAREPOINT_CONFIG_FILE = REFERENCIAS_DIR / "fuente_orden_reporte.json"
REPORTES_DIR = BASE_DIR / "reportes"

# Todo lo descargado de Dynamo vive bajo una sola carpeta raiz, organizada
# como descargas/<tabla>/<ambiente>/<YYYY-MM-DD>/, en vez de esparcirse en
# la raiz del proyecto con el nombre literal (y larguisimo) de cada tabla.
DESCARGAS_DIR = BASE_DIR / "descargas"
DATE_FORMAT = "%Y-%m-%d"

ENVIRONMENTS = ("qa", "pdn", "dev")

# Las dos (unicas) tablas soportadas por el pipeline. La carpeta local de
# cada una es simplemente su nombre corto (table_key); el nombre real de
# la tabla en Dynamo se arma con name_template.
TABLE_DEFS = {
    "config-control": {
        "name_template": "nu0087001-aid-r2-{env}-dynamo-config-control",
    },
    "text-analyzer": {
        "name_template": "nu0600001-plataforma-ia-{env}-text-analyzer-table",
    },
    "events-manager": {
        "name_template": "nu6490001-udz-{env}-events-manager-table",
    },
}

# Nombres de carpeta usados por el pipeline ANTES de esta reorganizacion.
# Solo se usan para autodetectar y seguir aprovechando descargas viejas
# como referencia; el codigo nuevo ya no escribe aqui.
LEGACY_FOLDERS = {
    "config-control": "nu0087001-aid-r2-ENV-dynamo-config-control",
    "text-analyzer": "nu0600001-plataforma-ia-ENV-text-analyzer-table",
}


def _load_pipeline_config() -> dict:
    if not PIPELINE_CONFIG_FILE.exists():
        logger.warning(
            "No existe %s; se usaran observaciones manuales y orden de reporte vacios.",
            PIPELINE_CONFIG_FILE,
        )
        return {"manual_observations": {}, "orden_reporte_subtipos": []}
    return json.loads(PIPELINE_CONFIG_FILE.read_text(encoding="utf-8"))


_PIPELINE_CONFIG = _load_pipeline_config()

MANUAL_OBSERVATIONS: Dict[str, str] = _PIPELINE_CONFIG.get("manual_observations", {})

# Por defecto usa la lista estatica de pipeline_config.json. Si existe
# referencias/fuente_orden_reporte.json con "activo": true, se reemplaza
# por lo que haya en la columna configurada del Excel maestro.
ORDEN_REPORTE_SUBTIPOS: List[str] = sharepoint_source.load_orden_reporte(
    SHAREPOINT_CONFIG_FILE, fallback=_PIPELINE_CONFIG.get("orden_reporte_subtipos", [])
)


def resolve_table_name(table_key: str, environment: str) -> str:
    """Devuelve el nombre real de la tabla en DynamoDB."""
    if table_key not in TABLE_DEFS:
        raise ValueError(f"Tabla invalida '{table_key}'. Opciones: {list(TABLE_DEFS)}")
    if environment not in ENVIRONMENTS:
        raise ValueError(f"Ambiente invalido '{environment}'. Opciones: {ENVIRONMENTS}")

    return TABLE_DEFS[table_key]["name_template"].format(env=environment)


def download_dir(table_key: str, environment: str, date_stamp: str) -> Path:
    """Carpeta donde se guarda una descarga: descargas/<tabla>/<ambiente>/<fecha>/."""
    return DESCARGAS_DIR / table_key / environment / date_stamp
