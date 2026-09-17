"""
Utilidades compartidas por todo el pipeline.

Antes esta logica estaba duplicada: una version en jq/awk dentro de
compare_r3_vs_text_analyzer.sh y otra version en verificar_repetidos.py.
Aqui queda en un solo lugar y todos los pasos la importan.
"""
from __future__ import annotations

import json
import re
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def human_date(dt: datetime) -> str:
    """'15 de septiembre de 2026', sin depender del locale del sistema
    (que en Windows suele venir en ingles y romper los nombres de mes)."""
    return f"{dt.day} de {_MESES[dt.month - 1]} de {dt.year}"


def human_datetime(dt: datetime) -> str:
    """'15 de septiembre de 2026, 09:25 PM'."""
    hora = dt.strftime("%I:%M %p").lstrip("0") or dt.strftime("%I:%M %p")
    return f"{human_date(dt)}, {hora}"


def classify_udz_tipo(s3_path: str) -> Optional[str]:
    """Para la tabla events-manager (UDZ): identifica si un s3_path es de
    'crudos' o de 'resultados' (transmisiones). Devuelve None si no matchea
    ninguno de los dos patrones conocidos."""
    if "/crudos/" in s3_path:
        return "crudos"
    if "/resultados/" in s3_path:
        return "resultados"
    return None


def udz_flow_key(s3_path: str, tipo: str) -> str:
    """Parte del s3_path que identifica el flujo, sin importar si esta en
    crudos/ o resultados/ (para poder emparejar ambos). Ejemplo: de
    '.../crudos/ns_apoyo_corporativo/EVOLUCIONDIGITAL_SEGURODEACTIVO'
    devuelve 'ns_apoyo_corporativo/EVOLUCIONDIGITAL_SEGURODEACTIVO'."""
    marker = f"/{tipo}/"
    idx = s3_path.find(marker)
    if idx == -1:
        return s3_path
    return s3_path[idx + len(marker):].rstrip("/")


def normalize_text(value: Any) -> str:
    """Minusculas, sin tildes, sin simbolos. Usado para comparar subtipos
    aunque vengan con mayusculas/tildes/espacios distintos."""
    text = str(value or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def sanitize_filename(value: str) -> str:
    """Equivalente a sanitize_filename() en download_from_dynamo.sh."""
    for bad in ('/', ':', ' ', '?', '*', '"', '<', '>', '|'):
        value = value.replace(bad, '_' if bad in ('/', ':', ' ') else '')
    return value


def sanitize_csv_field(value: Optional[str]) -> str:
    """Evita que \\r, \\n o ';' rompan el CSV delimitado por punto y coma."""
    value = value or ""
    value = value.replace('\r', ' ').replace('\n', ' ')
    return value.replace(';', ',')


def walk_nodes(data: Any) -> Iterator[dict]:
    """Recorrido pre-order de todos los dict anidados (dentro de dicts o
    listas). Es el equivalente Python de la expresion jq `.. | objects`."""
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from walk_nodes(value)
    elif isinstance(data, list):
        for item in data:
            yield from walk_nodes(item)


def find_key_recursive(data: Any, target_key: str) -> Any:
    """Busca la PRIMERA aparicion de una clave con ese nombre en cualquier
    nivel del JSON (dict o lista anidada). Replica find_key_recursive()
    de verificar_repetidos.py."""
    if isinstance(data, dict):
        if target_key in data:
            return data[target_key]
        for value in data.values():
            found = find_key_recursive(value, target_key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_key_recursive(item, target_key)
            if found is not None:
                return found
    return None


def first_nested_value(data: Any, container_key: str, field_key: str) -> str:
    """Busca, en cualquier nivel, un dict que tenga `container_key` (p.ej.
    'STEP_VARIABLES') y dentro de ese sub-dict el campo `field_key` (p.ej.
    'use_case'). Devuelve el primero no vacio. Replica la consulta jq:
    `[.. | objects | .STEP_VARIABLES? | .use_case? // empty] | first`."""
    for node in walk_nodes(data):
        container = node.get(container_key)
        if isinstance(container, dict):
            value = container.get(field_key)
            if value not in (None, ""):
                return str(value)
    return ""


def has_nested_key(data: Any, key: str) -> bool:
    """True si algun dict anidado tiene esa clave. Replica:
    `.. | objects | select(has("use_case"))`."""
    for node in walk_nodes(data):
        if key in node:
            return True
    return False


def has_topic_step(data: Any) -> bool:
    """True si algun workflow_definition[].THREADS[].STEPS[].TYPE == 'topic'.
    Replica la sub-clasificacion R3/topics vs R3/ms del script de descarga."""
    if not isinstance(data, dict):
        return False
    for wf in data.get("workflow_definition") or []:
        if not isinstance(wf, dict):
            continue
        for thread in wf.get("THREADS") or []:
            if not isinstance(thread, dict):
                continue
            for step in thread.get("STEPS") or []:
                if isinstance(step, dict) and step.get("TYPE") == "topic":
                    return True
    return False


def get_workflow_variable(data: dict, key: str) -> str:
    """Primero busca en workflow_variables.<key>; si no esta, busca esa
    clave en cualquier parte del JSON. Replica get_workflow_variable() de
    verificar_repetidos.py."""
    workflow_variables = data.get("workflow_variables", {})
    if isinstance(workflow_variables, dict):
        value = workflow_variables.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()

    value = find_key_recursive(data, key)
    if value is not None and str(value).strip():
        return str(value).strip()
    return ""


def get_tipo_documento(data: dict) -> str:
    return get_workflow_variable(data, "tipoDocumento") or "SIN_TIPODOCUMENTO"


def get_proceso(data: dict) -> str:
    return get_workflow_variable(data, "proceso") or "SIN_PROCESO"


def get_use_case(data: dict) -> str:
    return first_nested_value(data, "STEP_VARIABLES", "use_case")


def get_subtipo_workflow_variables(data: dict) -> str:
    return first_nested_value(data, "workflow_variables", "tipoDocumento") or "REVISAR_MANUAL"


def basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _decode_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def iter_json_files(path_str: str) -> Iterator[tuple[str, str]]:
    """Itera (ruta, contenido_texto) sobre JSONs en una carpeta o dentro de
    un ZIP (acepta 'archivo.zip/carpeta/interna' como en verificar_repetidos.py)."""
    clean_path = path_str.strip().strip('"')
    lower_path = clean_path.lower()
    zip_index = lower_path.find(".zip")

    if zip_index != -1:
        zip_path = Path(clean_path[: zip_index + 4])
        inner_prefix = clean_path[zip_index + 4:].lstrip("\\/").replace("\\", "/")
        if not zip_path.exists():
            raise FileNotFoundError(f"No existe el ZIP: {zip_path}")
        with zipfile.ZipFile(zip_path, "r") as zf:
            wanted_prefix = inner_prefix.rstrip("/") + "/" if inner_prefix else ""
            for member in zf.namelist():
                member_norm = member.replace("\\", "/")
                if wanted_prefix and not member_norm.startswith(wanted_prefix):
                    continue
                if not member_norm.lower().endswith(".json"):
                    continue
                with zf.open(member) as fh:
                    yield member_norm, _decode_bytes(fh.read())
        return

    path = Path(clean_path)
    if path.is_dir():
        for json_file in path.rglob("*.json"):
            yield str(json_file), json_file.read_text(encoding="utf-8-sig", errors="replace")
        return

    raise FileNotFoundError(f"No existe la ruta o no es valida: {path_str}")


def load_json_files(directory: Path) -> Iterator[tuple[Path, dict]]:
    """Version simple para directorios reales (no ZIP): (ruta, dict)."""
    for json_file in sorted(directory.rglob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception:
            data = {}
        yield json_file, data if isinstance(data, dict) else {}
