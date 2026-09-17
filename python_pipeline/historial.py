"""
Maestro acumulado por ambiente: guarda el estado COMPLETO conocido de
cada flujo (los mismos campos del Reporte Agrupado), independiente de
cualquier corrida puntual. Es lo que responde "que tenemos hoy en qa/pdn"
sin importar si la ultima descarga fue completa o incremental.

Se guarda por ambiente (qa/pdn/dev no se mezclan):
  historial/<ambiente>/estado_actual.json  -> snapshot mas reciente conocido
  historial/<ambiente>/eventos.json        -> log append-only de cada cambio
                                               (estado interno; el reporte
                                               que se lee es el Excel que
                                               genera export_excel())

Dos modos de actualizacion (ver `modo` en actualizar()):
  - "incremental" (default): filas_actuales trae SOLO lo que se descargo
    en esta corrida (puede ser un subconjunto chico, si la descarga fue
    incremental). Se agregan/actualizan esos flujos; los que no aparecen
    NO se tocan -- no hay forma de saber si siguen existiendo o no con
    datos parciales, asi que nunca se marcan ELIMINADO en este modo.
  - "completo": filas_actuales es la foto 100% completa de la tabla (la
    descarga se hizo con --modo-descarga completo). Cualquier flujo que
    estaba presente y ya no aparece SI se marca ELIMINADO.

No requiere que el usuario haga nada: se actualiza solo cada vez que
corre el pipeline completo.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import config

logger = logging.getLogger(__name__)

HISTORIAL_DIR = config.BASE_DIR / "historial"

# Campos que se guardan tal cual (para poder reconstruir el maestro en
# formato Reporte Agrupado) vs. los que realmente importan para decidir
# si un flujo "cambio" de una corrida a otra.
_CAMPOS_GUARDADOS = ("ta_config", "subtipo", "proceso", "s3_path", "observacion", "transmisiones", "tipo")
_CAMPOS_COMPARADOS = ("subtipo", "ta_config", "transmisiones", "tipo")


def _estado_file(environment: str) -> Path:
    return HISTORIAL_DIR / environment / "estado_actual.json"


def _eventos_file(environment: str) -> Path:
    return HISTORIAL_DIR / environment / "eventos.json"


def _load_estado(environment: str) -> Dict[str, dict]:
    path = _estado_file(environment)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("No se pudo leer el estado previo (%s); se trata como si no hubiera historial.", exc)
        return {}


def _save_estado(environment: str, estado: Dict[str, dict]) -> None:
    path = _estado_file(environment)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_eventos(environment: str) -> List[dict]:
    path = _eventos_file(environment)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("No se pudo leer el log de eventos previo (%s); se parte de uno vacio.", exc)
        return []


def _append_eventos(environment: str, eventos: List[dict]) -> None:
    if not eventos:
        return
    completos = _load_eventos(environment)
    completos.extend(eventos)
    path = _eventos_file(environment)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(completos, ensure_ascii=False, indent=2), encoding="utf-8")


def actualizar(environment: str, filas_actuales: List[dict], modo: str = "incremental", fecha: str = None) -> dict:
    """filas_actuales: lista de dicts con 'file' + los campos de
    group_report.snapshot_rows (subtipo, ta_config, proceso, s3_path,
    observacion, transmisiones, tipo). Devuelve un resumen
    {nuevos, eliminados, cambios} (listas de nombres) y deja el maestro
    actualizado en disco (estado_actual.json + eventos.json)."""
    if modo not in ("incremental", "completo"):
        raise ValueError(f"modo invalido: {modo!r} (usa 'incremental' o 'completo')")

    fecha = fecha or datetime.now().strftime(config.DATE_FORMAT)

    estado = _load_estado(environment)
    eventos: List[dict] = []
    nuevos: List[str] = []
    cambios: List[str] = []

    vistos_hoy = set()
    for fila in filas_actuales:
        nombre = fila["file"]
        vistos_hoy.add(nombre)
        snapshot = {campo: fila.get(campo, "") for campo in _CAMPOS_GUARDADOS}
        previo = estado.get(nombre)

        snapshot["presente"] = True
        snapshot["primera_vez"] = previo.get("primera_vez", fecha) if previo else fecha
        snapshot["ultima_vez"] = fecha

        if previo is None:
            nuevos.append(nombre)
            eventos.append({
                "fecha": fecha, "flujo": nombre, "tipo": "NUEVO",
                "detalle": f"subtipo={snapshot['subtipo']}",
            })
        else:
            diffs = [
                f"{campo}: '{previo.get(campo, '')}' -> '{snapshot[campo]}'"
                for campo in _CAMPOS_COMPARADOS
                if previo.get(campo, "") != snapshot[campo]
            ]
            if diffs:
                cambios.append(nombre)
                eventos.append({"fecha": fecha, "flujo": nombre, "tipo": "CAMBIO", "detalle": "; ".join(diffs)})

        estado[nombre] = snapshot

    eliminados: List[str] = []
    if modo == "completo":
        for nombre, snapshot in estado.items():
            if snapshot.get("presente") and nombre not in vistos_hoy:
                snapshot["presente"] = False
                eliminados.append(nombre)
                eventos.append({
                    "fecha": fecha, "flujo": nombre, "tipo": "ELIMINADO",
                    "detalle": "ya no aparece en la descarga completa mas reciente",
                })

    _save_estado(environment, estado)
    _append_eventos(environment, eventos)

    resumen = {"nuevos": nuevos, "eliminados": eliminados, "cambios": cambios}
    logger.info(
        "Maestro actualizado (%s, modo=%s): %s nuevos, %s eliminados, %s con cambios.",
        environment, modo, len(nuevos), len(eliminados), len(cambios),
    )
    return resumen


def eventos_completos(environment: str) -> List[dict]:
    """El log acumulado completo (todas las corridas anteriores incluidas),
    para exportarlo a Excel con excel_report.build_historial_workbook."""
    return _load_eventos(environment)


def flujos_presentes(environment: str) -> List[dict]:
    """Lista de dicts (file + todos los campos guardados) para los flujos
    actualmente presentes (presente=True) en el maestro de este ambiente.
    Lista para pasar a group_report.group_rows()."""
    estado = _load_estado(environment)
    filas = []
    for nombre, snapshot in estado.items():
        if snapshot.get("presente"):
            fila = {"file": nombre}
            fila.update({campo: snapshot.get(campo, "") for campo in _CAMPOS_GUARDADOS})
            filas.append(fila)
    return filas
