"""
Fuente opcional para el orden del reporte: en vez de mantener la lista a
mano en referencias/pipeline_config.json, se puede leer directamente de
una columna de un Excel maestro (el mismo que vive en SharePoint).

Como funciona:
  No hay conexion "en la nube" de verdad: SharePoint, cuando lo sincronizas
  con OneDrive, aparece como una carpeta normal de Windows (algo como
  "C:/Users/tu.usuario/OneDrive - Empresa/Documentos/Maestro.xlsx"). El
  pipeline simplemente abre ESE archivo local con openpyxl, exactamente
  igual que abre cualquier otro .xlsx. No hace falta ninguna API, token
  ni login especial: si OneDrive esta sincronizando esa carpeta en la
  maquina donde corres el pipeline, el archivo esta ahi.

  Si el dia de manana esto corre en un servidor SIN OneDrive instalado,
  ahi si haria falta la API de Microsoft Graph (mucho mas trabajo:
  registrar una app en Azure AD, permisos, tokens) - pero mientras corra
  en una maquina con OneDrive sincronizado, este metodo simple alcanza.

Configuracion (referencias/fuente_orden_reporte.json):
  "activo": true/false           -> prende o apaga esta fuente
  "ruta_archivo": ruta local del Excel maestro (ver ejemplo arriba)
  "hoja": nombre EXACTO de la pestana dentro del Excel
  "columna": encabezado EXACTO de la columna que trae el orden
  "fila_encabezado": en que fila esta ese encabezado (normalmente 1)

Si "activo" es false, el archivo no existe, o algo falla al leerlo
(ruta no sincronizada, hoja/columna renombrada, etc.), se usa la lista
estatica de pipeline_config.json como respaldo y se deja un aviso en el
log - el pipeline NUNCA se cae por esto.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def _read_column(ruta_archivo: Path, hoja: str, columna: str, fila_encabezado: int) -> List[str]:
    from openpyxl import load_workbook

    if not ruta_archivo.exists():
        raise FileNotFoundError(str(ruta_archivo))

    wb = load_workbook(ruta_archivo, read_only=True, data_only=True)
    if hoja not in wb.sheetnames:
        raise ValueError(f"La hoja '{hoja}' no existe en {ruta_archivo}. Hojas disponibles: {wb.sheetnames}")
    ws = wb[hoja]

    header_row = next(ws.iter_rows(min_row=fila_encabezado, max_row=fila_encabezado, values_only=True), ())
    col_index = None
    for idx, value in enumerate(header_row):
        if value and str(value).strip().lower() == columna.strip().lower():
            col_index = idx
            break
    if col_index is None:
        raise ValueError(f"No se encontro la columna '{columna}' en la fila {fila_encabezado} de la hoja '{hoja}'.")

    valores: List[str] = []
    for row in ws.iter_rows(min_row=fila_encabezado + 1, values_only=True):
        if col_index < len(row) and row[col_index] not in (None, ""):
            valores.append(str(row[col_index]).strip())
    return valores


def load_orden_reporte(config_file: Path, fallback: List[str]) -> List[str]:
    """Punto de entrada usado por config.py. Nunca lanza excepcion: ante
    cualquier problema devuelve `fallback` (la lista estatica de
    pipeline_config.json)."""
    if not config_file.exists():
        return fallback

    try:
        settings = json.loads(config_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("No se pudo leer %s (%s); se usa la lista estatica.", config_file, exc)
        return fallback

    if not settings.get("activo"):
        return fallback

    try:
        ruta_archivo = Path(settings["ruta_archivo"])
        hoja = settings["hoja"]
        columna = settings["columna"]
        fila_encabezado = int(settings.get("fila_encabezado", 1))
    except KeyError as exc:
        logger.warning("Falta la clave %s en %s; se usa la lista estatica.", exc, config_file)
        return fallback

    try:
        valores = _read_column(ruta_archivo, hoja, columna, fila_encabezado)
    except FileNotFoundError:
        logger.warning(
            "No se encontro el Excel maestro en %s (¿esta sincronizado OneDrive/SharePoint "
            "en esta maquina?); se usa la lista estatica.", ruta_archivo,
        )
        return fallback
    except Exception as exc:
        logger.warning("No se pudo leer el orden desde el Excel maestro (%s); se usa la lista estatica.", exc)
        return fallback

    if not valores:
        logger.warning(
            "La columna '%s' en %s / hoja '%s' esta vacia; se usa la lista estatica.",
            columna, ruta_archivo, hoja,
        )
        return fallback

    logger.info(
        "Orden de reporte cargado desde el Excel maestro (%s, hoja '%s', columna '%s'): %s nombres.",
        ruta_archivo, hoja, columna, len(valores),
    )
    return valores
