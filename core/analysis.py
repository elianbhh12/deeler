"""Motor de validación: lee TA/AID/UDZ y calcula si una HU está LISTO/ERROR/INCOMPLETO.

Es el módulo más importante del proyecto — acá viven las 12 validaciones
críticas (ver config.VALIDATION_KEYS) que deciden si una HU puede aprobarse
para PDN. `cargar_json` usa `st.warning` para avisar de JSON inválido; fuera
de eso, este módulo no tiene layout ni widgets de Streamlit.
"""
import json
from pathlib import Path
from datetime import datetime

import streamlit as st

from .config import (
    ICON_OK, ICON_ERROR, ICON_WARNING, ICON_NA,
    ESTADO_LISTO, ESTADO_ERROR, ESTADO_INCOMPLETO, ESTADO_SIN_METADATA,
    ESTADO_ICON, ESTADO_TEXTO, VALIDATION_KEYS, KAFKA_TOPIC_REQUERIDO,
    AID_TYPE_VALIDOS, MI_WARNING,
)
from .utils import obtener_usuario_actual


#  Estado (código lógico, separado del ícono de presentación)

def estado_display(code: str) -> str:
    """Texto a mostrar (ícono + etiqueta) para un código de estado."""
    return f"{ESTADO_ICON.get(code, ICON_NA)} {ESTADO_TEXTO.get(code, code)}"


def get_estado_code(r: dict) -> str:
    """Código de estado robusto para lógica/filtros.

    Usa 'estado_code' si el resultado lo trae; si no (análisis guardados con una
    versión anterior que solo tenía el texto con ícono), lo infiere de 'estado_general'.
    """
    code = r.get("estado_code")
    if code:
        return code
    texto = r.get("estado_general", "")
    if ICON_OK in texto:
        return ESTADO_LISTO
    if ICON_ERROR in texto:
        return ESTADO_ERROR
    if ICON_WARNING in texto:
        return ESTADO_INCOMPLETO
    return ESTADO_SIN_METADATA


def _val_ok(v: dict) -> bool:
    """Extrae el resultado 'ok' de una validación. out_zone_copiar no tiene una
    clave 'ok' propia (usa out_zone_ok + copiar_ok), así que se calcula aparte."""
    if "out_zone_ok" in v:
        return bool(v.get("out_zone_ok", True)) and bool(v.get("copiar_ok", True))
    return bool(v.get("ok", True))


#  Helpers de búsqueda en JSON

def buscar_clave(obj, key: str):
    """Busca recursivamente una clave en dicts/listas anidados. Retorna primer valor encontrado o None."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = buscar_clave(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = buscar_clave(item, key)
            if found is not None:
                return found
    return None


def buscar_clave_todos(obj, key: str, resultados_acc: list):
    """Busca recursivamente y acumula TODOS los valores de una clave."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                resultados_acc.append(v)
            else:
                buscar_clave_todos(v, key, resultados_acc)
    elif isinstance(obj, list):
        for item in obj:
            buscar_clave_todos(item, key, resultados_acc)


def cargar_json(path: Path):
    try:
        content = path.read_text(encoding="utf-8")
        return json.loads(content)
    except json.JSONDecodeError as e:
        st.warning(f"JSON inválido en `{path.name}`: {e}", icon=MI_WARNING)
        return None
    except (FileNotFoundError, OSError) as e:
        # En Windows, una ruta completa de más de ~260 caracteres da el mismo
        # "No such file or directory" que un archivo realmente inexistente —
        # aunque el archivo se vea perfecto en el Explorador. Si la ruta es
        # sospechosamente larga, se avisa explícitamente en vez de dejar
        # pensar que el archivo desapareció.
        if len(str(path)) > 240:
            st.warning(
                f"No se pudo abrir `{path.name}` — la ruta completa tiene {len(str(path))} caracteres "
                f"(límite de Windows: 260). Acortá ROOT_FOLDER en el .env para que la ruta completa "
                f"quede por debajo del límite.",
                icon=MI_WARNING,
            )
        else:
            st.warning(f"Error leyendo `{path.name}`: {e}", icon=MI_WARNING)
        return None
    except Exception as e:
        st.warning(f"Error leyendo `{path.name}`: {e}", icon=MI_WARNING)
        return None


#  Análisis

def normalizar_s3(p):
    return p.rstrip("/").strip() if p else ""


def detectar_ambiente(s3):
    s = s3.lower()
    if "-pdn-" in s or "-prod-" in s: return "PDN"
    if "-qa-"  in s: return "QA"
    if "-dev-" in s: return "DEV"
    if "-uat-" in s: return "UAT"
    return "DESCONOCIDO"


def inferir_tipo_config(data) -> str:
    """Determina el tipo de un JSON genérico por su estructura interna.

    AID:  raíz tiene workflow_definition (lista) + workflow_name + s3_path
    TA:   raíz (o dentro de item{}) tiene cu_name + data + resource_name
          O es array [{data:{aio, text_querys, answer_generator}}]
    UDZ:  raíz plana con consumer_app + id + topic + s3_path (sin item wrapper)
    """
    if not isinstance(data, (dict, list)):
        return "desconocido"
    root = data[0] if isinstance(data, list) and data else data
    if not isinstance(root, dict):
        return "desconocido"
    keys = set(root.keys())

    #  AID: workflow_definition es la clave definitiva
    if "workflow_definition" in keys:
        return "AID"

    #  UDZ: plano, consumer_app + id + topic en raíz
    if "consumer_app" in keys and "id" in keys and "topic" in keys:
        return "UDZ"

    #  TA v2 plano: cu_name + data + resource_name en raíz
    if "cu_name" in keys and "data" in keys and "resource_name" in keys:
        return "TA"

    #  TA v1: envuelto en item{} con cu_name
    if "item" in keys and isinstance(root.get("item"), dict):
        item_k = set(root["item"].keys())
        if "cu_name" in item_k:
            return "TA"

    #  TA config.json: array [{data:{aio/text_querys/answer_generator}}]
    if "data" in keys and isinstance(root.get("data"), dict):
        inner = set(root["data"].keys())
        if "aio" in inner or "text_querys" in inner or "answer_generator" in inner:
            return "TA"

    return "desconocido"


def clasificar_udz_desde_json(udz_data: dict) -> str:
    """Clasifica UDZ en RESULTADOS o CRUDOS según flags y s3_path."""
    if not isinstance(udz_data, dict):
        return "DESCONOCIDO"
    item = udz_data.get("item") if isinstance(udz_data.get("item"), dict) else udz_data
    req = str(item.get("require_transmission", "")).strip().lower() == "true"
    s3_path = str(item.get("s3_path", "")).lower()
    if req or "resultados" in s3_path:
        return "RESULTADOS"
    if "crudos" in s3_path:
        return "CRUDOS"
    return "DESCONOCIDO"


def detectar_slots_udz(r: dict) -> list:
    """Determina en cuántos "slots" de subida a AWS se separa el UDZ de esta
    HU. Un UDZ es CRUDOS (entrada) o RESULTADOS/transmisión (salida) — casi
    siempre la HU trae un solo archivo UDZ (un slot), pero a veces trae los
    dos por separado como archivos distintos, y ahí cada uno se sube y se
    trackea por su cuenta (a veces solo hace falta uno de los dos, ej. un
    flujo que solo lee crudos sin publicar transmisión de resultados).

    Devuelve una lista de dicts {"tipo": "CRUDOS"/"RESULTADOS"/None,
    "archivo": str, "es_activo": bool} — "es_activo" indica si ese archivo es
    el mismo que `udz_activo` (el único que de verdad está validado ahora
    mismo por las 12 validaciones críticas; ver selector "UDZ a usar" en
    ui/hu_detail.py). Con un solo archivo, la lista siempre tiene 1 elemento
    (comportamiento de siempre); con crudos+resultados como archivos
    distintos, tiene 2."""
    udz_files = r.get("udz_files") or []
    udz_activo = r.get("udz_activo")

    if not udz_files:
        return [{"tipo": None, "archivo": udz_activo, "es_activo": True}]

    clasificados = []
    for p in udz_files:
        data = cargar_json(Path(p))
        tipo = clasificar_udz_desde_json(data) if data else "DESCONOCIDO"
        clasificados.append({"tipo": tipo, "archivo": str(p), "es_activo": str(p) == str(udz_activo)})

    tipos_presentes = {c["tipo"] for c in clasificados if c["tipo"] in ("CRUDOS", "RESULTADOS")}
    if len(tipos_presentes) < 2:
        # Un solo tipo detectado entre los archivos (o ninguno clasificable)
        # — se mantiene el comportamiento de siempre: un solo slot, con el
        # archivo activo elegido en el análisis.
        tipo_unico = next(iter(tipos_presentes), None)
        return [{"tipo": tipo_unico, "archivo": udz_activo, "es_activo": True}]

    # CRUDOS y RESULTADOS como archivos distintos — dos slots independientes.
    slots = []
    for tipo in ("CRUDOS", "RESULTADOS"):
        c = next((c for c in clasificados if c["tipo"] == tipo), None)
        if c:
            slots.append(c)
    return slots


def obtener_estado_pdn_real(r: dict) -> dict:
    """Si la HU realmente quedó desplegada en PDN — no un checkbox que
    cualquiera puede marcar, sino el hecho de que TODOS sus componentes
    presentes (TA/AID/UDZ, incluyendo ambos slots si hay crudos+resultados
    separados) ya se subieron con éxito a la tabla de PDN (ver
    ui.aws_console._persistir_subida_aws, que graba `{clave}_aws_ambiente`
    y `{clave}_aws_por` en cada subida real).

    Devuelve {"desplegado": bool, "por": str|None, "en": str|None} — "por"/"en"
    son de la última subida entre los componentes (quien cerró el despliegue)."""
    componentes = []
    if r.get("ta_activo"):
        componentes.append("ta")
    if r.get("aid_activo"):
        componentes.append("aid")
    slots = detectar_slots_udz(r)
    for s in slots:
        if not s["archivo"]:
            continue
        clave = f"udz_{s['tipo'].lower()}" if (s["tipo"] and len(slots) > 1) else "udz"
        componentes.append(clave)

    if not componentes:
        return {"desplegado": False, "por": None, "en": None}

    subidas = []
    for clave in componentes:
        if r.get(f"{clave}_aws_ambiente") != "pdn" or not r.get(f"{clave}_aws_por"):
            return {"desplegado": False, "por": None, "en": None}
        subidas.append((r.get(f"{clave}_aws_en") or "", r.get(f"{clave}_aws_por")))

    subidas.sort()
    _en, _por = subidas[-1]
    return {"desplegado": True, "por": _por, "en": _en}


def buscar_archivos(hu_folder: Path):
    adj = hu_folder / "adjuntos"
    res = {"ta": None, "aid": None, "udz": None, "ta_files": [], "aid_files": [], "udz_files": [], "configs_sin_tipo": []}
    if not adj.exists():
        return res
    for f in adj.iterdir():
        if f.suffix != ".json":
            continue
        if f.name.startswith("._"):
            # Metadata "fantasma" que deja un ZIP armado en Mac (resource fork)
            # — no es contenido real. Ya se filtra al descomprimir
            # (core/ado_client.py), esto es una segunda barrera por si el
            # archivo ya estaba en disco de una descarga anterior a ese fix.
            continue
        stem = f.stem.lower()

        # 1. Detecta por nombre (más confiable)
        if "aid" in stem:
            if res["aid"] is None:
                res["aid"] = f
            res["aid_files"].append(f)
        elif "udz" in stem:
            if res["udz"] is None:
                res["udz"] = f
            res["udz_files"].append(f)
        elif "ta" in stem:
            if res["ta"] is None:
                res["ta"] = f
            res["ta_files"].append(f)
        else:
            # 2. Nombre genérico (config.json, etc.) — inferir por estructura
            try:
                data = cargar_json(f)
                tipo = inferir_tipo_config(data)
            except Exception:
                tipo = "desconocido"

            if tipo == "AID":
                if res["aid"] is None:
                    res["aid"] = f
                res["aid_files"].append(f)
                res["configs_sin_tipo"].append({"archivo": f, "tipo_inferido": tipo, "auto_asignado": True})
            elif tipo == "TA":
                if res["ta"] is None:
                    res["ta"] = f
                res["ta_files"].append(f)
                res["configs_sin_tipo"].append({"archivo": f, "tipo_inferido": tipo, "auto_asignado": True})
            elif tipo == "UDZ":
                if res["udz"] is None:
                    res["udz"] = f
                res["udz_files"].append(f)
                res["configs_sin_tipo"].append({"archivo": f, "tipo_inferido": tipo, "auto_asignado": True})
            else:
                res["configs_sin_tipo"].append({"archivo": f, "tipo_inferido": tipo, "auto_asignado": False})

    # Unificar y deduplicar listas de TA/AID/UDZ detectados
    for clave in ("ta", "aid", "udz"):
        lista = res[f"{clave}_files"]
        if res[clave] and res[clave] not in lista:
            lista.append(res[clave])
        _seen = set()
        _uniq = []
        for p in lista:
            if str(p) not in _seen:
                _seen.add(str(p))
                _uniq.append(p)
        res[f"{clave}_files"] = _uniq
    return res


def buscar_rnf(hu_folder: Path):
    """Busca archivo RNF*.xlsx en adjuntos"""
    adj = hu_folder / "adjuntos"
    if not adj.exists():
        return None
    for f in adj.iterdir():
        if f.suffix.lower() in [".xlsx", ".xls"]:
            n = f.name.lower()
            if "rnf" in n:
                return f
    return None


def _validar_udz_cruzadas(aid: dict, wf: str, aid_s3: str, udz: dict, es_despliegue: bool) -> dict:
    """Las 4 validaciones que cruzan AID con un UDZ puntual (s3_path,
    workflow_vs_id, ambiente_workflow_id, udz_transmisiones). Factorizado
    para poder correrlo tanto sobre el UDZ activo (las validaciones
    "oficiales" de la HU) como sobre el otro archivo UDZ cuando la HU trae
    crudos y resultados por separado — así ambos quedan realmente validados
    y no hace falta alternar cuál está activo para poder subir los dos a AWS."""
    _udz_item = udz.get("item") if udz else None
    _udz_root = udz if isinstance(udz, dict) else {}
    udz_s3 = (_udz_item.get("s3_path", "") if isinstance(_udz_item, dict) else "") or _udz_root.get("s3_path", "")
    udz_require_transmission = (_udz_item.get("require_transmission") if isinstance(_udz_item, dict) else None)
    if udz_require_transmission is None:
        udz_require_transmission = _udz_root.get("require_transmission")
    udz_emit_event = (_udz_item.get("emit_event") if isinstance(_udz_item, dict) else None)
    if udz_emit_event is None:
        udz_emit_event = _udz_root.get("emit_event")
    udz_id = (_udz_item.get("id", "") if isinstance(_udz_item, dict) else "") or _udz_root.get("id", "")

    # s3_path: CRUDOS exige ruta idéntica a AID; RESULTADOS exige la misma
    # ruta con "crudos" -> "resultados" (ver nota en analizar_hu original).
    _udz_tipo_s3 = clasificar_udz_desde_json(udz) if udz else "DESCONOCIDO"
    s3_na = not (aid_s3 and udz_s3)
    if aid_s3 and udz_s3:
        if _udz_tipo_s3 == "RESULTADOS":
            s3_esperado = normalizar_s3(aid_s3).replace("crudos", "resultados")
        else:
            s3_esperado = normalizar_s3(aid_s3)
        s3_ok = s3_esperado == normalizar_s3(udz_s3)
    else:
        s3_ok = not es_despliegue
        s3_esperado = normalizar_s3(aid_s3) if aid_s3 else ""
    val_s3_path = {
        "ok": s3_ok, "na": s3_na and not es_despliegue,
        "aid": aid_s3, "udz": udz_s3, "tipo_udz": _udz_tipo_s3, "esperado": s3_esperado,
        "detalle": f"{ICON_OK} s3_path coinciden" if s3_ok else f"{ICON_ERROR} AID: {aid_s3} | UDZ: {udz_s3}",
    }

    wf_na = not (wf and udz_id)
    wf_ok = (wf == udz_id) if (wf and udz_id) else (not es_despliegue)
    val_workflow_vs_id = {
        "ok": wf_ok, "na": wf_na and not es_despliegue,
        "workflow_name": wf, "udz_id": udz_id,
        "detalle": f"{ICON_OK} {wf}" if wf_ok else f"{ICON_ERROR} AID: {wf} | UDZ: {udz_id}",
    }

    aid_amb_wf = detectar_ambiente(wf) if wf else "DESCONOCIDO"
    udz_amb_id = detectar_ambiente(udz_id) if udz_id else "DESCONOCIDO"
    amb_wf_na = not (wf and udz_id)
    amb_wf_ok = (aid_amb_wf == udz_amb_id) if (wf and udz_id) else (not es_despliegue)
    val_ambiente_workflow_id = {
        "ok": amb_wf_ok, "na": amb_wf_na and not es_despliegue,
        "aid_workflow_name": wf, "udz_id": udz_id,
        "aid_ambiente": aid_amb_wf, "udz_ambiente": udz_amb_id,
        "detalle": f"{ICON_OK} Ambiente consistente" if amb_wf_ok else f"{ICON_ERROR} AID={aid_amb_wf} | UDZ={udz_amb_id}",
    }

    udz_tx_na = not bool(udz)
    require_true = str(udz_require_transmission).strip().lower() == "true"
    emit_false = str(udz_emit_event).strip().lower() == "false"
    s3_has_resultados = "resultados" in str(udz_s3).lower()
    s3_has_crudos = "crudos" in str(udz_s3).lower()
    udz_tipo = "RESULTADOS" if require_true else ("CRUDOS" if s3_has_crudos else "NO_DEFINIDO")
    if udz:
        udz_tx_ok = (emit_false and s3_has_resultados) if require_true else True
    else:
        udz_tx_ok = not es_despliegue
    val_udz_transmisiones = {
        "ok": udz_tx_ok, "na": udz_tx_na and not es_despliegue,
        "udz_tipo": udz_tipo, "require_transmission": udz_require_transmission,
        "emit_event": udz_emit_event, "s3_path": udz_s3,
        "detalle": f"{ICON_OK} UDZ consistente con regla crudos/resultados" if udz_tx_ok else f"{ICON_ERROR} Si require_transmission=true: emit_event=false y s3_path debe contener 'resultados'",
    }

    return {
        "s3_path": val_s3_path,
        "workflow_vs_id": val_workflow_vs_id,
        "ambiente_workflow_id": val_ambiente_workflow_id,
        "udz_transmisiones": val_udz_transmisiones,
    }


def analizar_hu(hu_folder: Path, ta_override: Path = None, aid_override: Path = None, udz_override: Path = None) -> dict:
    """Analiza una HU. Si hay varios TA, AID o UDZ en adjuntos, por defecto se usa
    el primero que se encontró — `ta_override`/`aid_override`/`udz_override` permiten
    forzar cuál de los varios usar (para cuando el usuario elige uno específico en la UI)."""
    meta_path = hu_folder / "metadata.json"
    if not meta_path.exists():
        return {
            "hu_id": "?",
            "hu_title": str(hu_folder.name),
            "tipo_cambio": "DESCONOCIDO",
            "estado_code": ESTADO_SIN_METADATA,
            "estado_general": estado_display(ESTADO_SIN_METADATA),
            "resumen": [],
            "validaciones": {},
            "archivos": {},
            "attachments": [],
            "downloaded_at": ""
        }

    meta   = cargar_json(meta_path)
    hu_id  = meta.get("id", "?")
    title  = meta.get("title", "?")
    arcs   = buscar_archivos(hu_folder)

    # Si no se pasó un override explícito para esta llamada (ej. "Actualizar" o
    # "Re-analizar sprint"), se respeta la última elección de TA/UDZ guardada en
    # disco — así el usuario no tiene que re-elegir cada vez que hay varios.
    out_path = hu_folder / "analisis" / "analisis_tecnico.json"
    _anterior = cargar_json(out_path) if out_path.exists() else None
    if not ta_override and _anterior and _anterior.get("ta_activo"):
        _prev_ta = Path(_anterior["ta_activo"])
        if _prev_ta in arcs.get("ta_files", []):
            ta_override = _prev_ta
    if not aid_override and _anterior and _anterior.get("aid_activo"):
        _prev_aid = Path(_anterior["aid_activo"])
        if _prev_aid in arcs.get("aid_files", []):
            aid_override = _prev_aid
    if not udz_override and _anterior and _anterior.get("udz_activo"):
        _prev_udz = Path(_anterior["udz_activo"])
        if _prev_udz in arcs.get("udz_files", []):
            udz_override = _prev_udz

    if ta_override and ta_override in arcs.get("ta_files", []):
        arcs["ta"] = ta_override
    if aid_override and aid_override in arcs.get("aid_files", []):
        arcs["aid"] = aid_override
    if udz_override and udz_override in arcs.get("udz_files", []):
        arcs["udz"] = udz_override
    rnf    = buscar_rnf(hu_folder)
    ta     = cargar_json(arcs["ta"])  if arcs["ta"]  else None
    aid    = cargar_json(arcs["aid"]) if arcs["aid"] else None
    udz    = cargar_json(arcs["udz"]) if arcs["udz"] else None

    # Detectar si TA fue inferido desde config.json
    ta_inferido = False
    configs_sin_tipo = arcs.get("configs_sin_tipo", [])
    for cfg in configs_sin_tipo:
        if cfg.get("tipo_inferido") == "TA" and cfg.get("auto_asignado"):
            ta_inferido = True
            break

    resultado = {
        "hu_id": hu_id,
        "hu_title": title,
        "tipo_cambio": meta.get("tipo_cambio", "DESCONOCIDO"),
        "hu_folder": str(hu_folder),  # Convertir Path a string para serializar
        "rnf_path": str(rnf) if rnf else None,
        "ta_inferido": ta_inferido,  # Convertir Path a string
        "archivos": {
            "TA":  arcs["ta"].name  if arcs["ta"]  else f"{ICON_ERROR} NO EXISTE",
            "AID": arcs["aid"].name if arcs["aid"] else f"{ICON_ERROR} NO EXISTE",
            "UDZ": arcs["udz"].name if arcs["udz"] else f"{ICON_ERROR} NO EXISTE",
            "RNF": rnf.name if rnf else f"{ICON_WARNING} NO ENCONTRADO"
        },
        "ta_files": [str(p) for p in arcs.get("ta_files", [])],
        "aid_files": [str(p) for p in arcs.get("aid_files", [])],
        "udz_files": [str(p) for p in arcs.get("udz_files", [])],
        "ta_activo": str(arcs["ta"]) if arcs["ta"] else None,
        "aid_activo": str(arcs["aid"]) if arcs["aid"] else None,
        "udz_activo": str(arcs["udz"]) if arcs["udz"] else None,
        "attachments": meta.get("attachments", []),
        "downloaded_at": meta.get("downloaded_at", ""),
        "estado_ado": meta.get("state", "New"),
        "created_date": meta.get("created_date", ""),
        "changed_date": meta.get("changed_date", ""),
        "sprint": meta.get("iteration_path", "").split("\\")[-1] if meta.get("iteration_path") else "?",
        "configs_sin_tipo": [{"nombre": c["archivo"].name, "tipo_inferido": c["tipo_inferido"]} for c in arcs.get("configs_sin_tipo", [])],
        "validaciones": {},
        "resumen": []
    }

    tipo_cambio = meta.get("tipo_cambio", "DESCONOCIDO").upper()
    es_despliegue = "DESPLIEGUE" in tipo_cambio

    faltantes = [k for k, v in {"TA": ta, "AID": aid, "UDZ": udz}.items() if not v]
    # DESPLIEGUE requiere los 3 archivos sin excepción — se marca INCOMPLETO,
    # pero NO se corta acá: el análisis sigue de largo y calcula las 12
    # validaciones igual (cada una ya sabe tratar ta/aid/udz=None como error
    # cuando es_despliegue, ver los "(not es_despliegue)" de más abajo). Antes
    # se retornaba temprano con "validaciones" vacío, y como la UI usa
    # ok=True por default cuando no encuentra una clave, terminaba mostrando
    # "12 correctas" — al revés de lo que pasaba en realidad.
    incompleto_por_archivos = es_despliegue and bool(faltantes)
    if faltantes:
        if es_despliegue:
            for archivo in faltantes:
                resultado["resumen"].append(f"{ICON_ERROR} {archivo}: no existe — requerido para DESPLIEGUE")
        else:
            # MODIFICACIÓN: avisar pero continuar con los que hay
            for archivo in faltantes:
                resultado["resumen"].append(f"{ICON_WARNING} {archivo}: no adjuntado — solo se valida lo que llegó en la HU")

    # Las 4 validaciones cruzadas AID<->UDZ (s3_path, workflow_vs_id,
    # ambiente_workflow_id, udz_transmisiones), factorizadas en
    # _validar_udz_cruzadas: acá se corren para el UDZ activo (las
    # validaciones "oficiales" de la HU). Si la HU trae crudos y resultados
    # como archivos separados, más abajo se vuelven a correr para el otro
    # archivo, así ambos quedan realmente validados para poder subirlos a
    # AWS sin tener que alternar cuál está activo.
    aid_s3 = aid.get("s3_path","") if aid else ""
    wf = aid.get("workflow_name","") if aid else ""
    _cross_activo = _validar_udz_cruzadas(aid, wf, aid_s3, udz, es_despliegue)
    resultado["validaciones"]["s3_path"] = _cross_activo["s3_path"]
    resultado["validaciones"]["workflow_vs_id"] = _cross_activo["workflow_vs_id"]
    resultado["validaciones"]["ambiente_workflow_id"] = _cross_activo["ambiente_workflow_id"]
    resultado["validaciones"]["udz_transmisiones"] = _cross_activo["udz_transmisiones"]

    # UDZ trae crudos y resultados como archivos separados: validar también
    # el otro archivo (no solo el activo), para que la consola de AWS pueda
    # dejar subir los dos sin tener que alternar "UDZ a usar".
    _slots_udz = detectar_slots_udz(resultado)
    if len(_slots_udz) > 1:
        resultado["validaciones_udz_extra"] = {}
        for _slot in _slots_udz:
            if _slot["es_activo"] or not _slot["archivo"]:
                continue
            _udz_otro = cargar_json(Path(_slot["archivo"]))
            _clave_extra = f"udz_{_slot['tipo'].lower()}" if _slot["tipo"] else "udz_otro"
            resultado["validaciones_udz_extra"][_clave_extra] = _validar_udz_cruzadas(
                aid, wf, aid_s3, _udz_otro, es_despliegue
            )

    # kafka - buscar TODAS las ocurrencias en la estructura (no solo la primera,
    # para detectar si algún step publica en un topic distinto al requerido)
    topic_vals = []
    if ta:
        buscar_clave_todos(ta, "kafka_output_topic", topic_vals)
    topic = topic_vals[0] if topic_vals else ""

    kf_na = not bool(ta)
    if topic_vals:
        kf_ok = all(t == KAFKA_TOPIC_REQUERIDO for t in topic_vals)
    elif not ta:
        kf_ok = not es_despliegue  # sin TA en MODIFICACIÓN → no bloquea (ya es N/A por kf_na)
    else:
        kf_ok = False  # TA existe pero no tiene kafka_output_topic — error real, no falso OK
    resultado["validaciones"]["kafka"] = {
        "ok": kf_ok,
        "na": kf_na and not es_despliegue,
        "topic": topic,
        "topics": topic_vals,
        "detalle": f"{ICON_OK} kafka_output_topic correcto" if kf_ok else f"{ICON_ERROR} Encontrado: {', '.join(topic_vals) if topic_vals else 'VACÍO'}"
    }

    # TA: cu_name obligatorio
    ta_cu_name = buscar_clave(ta, "cu_name") or "" if ta else ""
    ta_cu_na = not bool(ta)
    ta_cu_ok = bool(ta_cu_name) if ta else (not es_despliegue)
    resultado["validaciones"]["ta_cu_name"] = {
        "ok": ta_cu_ok,
        "na": ta_cu_na and not es_despliegue,
        "cu_name": ta_cu_name,
        "detalle": f"{ICON_OK} TA contiene cu_name" if ta_cu_ok else f"{ICON_ERROR} TA debe incluir 'cu_name'"
    }

    # TA: type debe ser "prompts"
    ta_type = buscar_clave(ta, "type") if ta else ""
    ta_type_na = not bool(ta)
    ta_type_ok = str(ta_type).strip().lower() == "prompts" if ta else (not es_despliegue)
    resultado["validaciones"]["ta_type_prompts"] = {
        "ok": ta_type_ok,
        "na": ta_type_na and not es_despliegue,
        "type": ta_type,
        "detalle": f"{ICON_OK} TA type='prompts'" if ta_type_ok else f"{ICON_ERROR} TA type inválido: {ta_type or 'VACÍO'}"
    }

    # AID: workflow_variables.tecnologia debe ser "AID"
    aid_tecnologia = ""
    if aid and isinstance(aid.get("workflow_variables"), dict):
        aid_tecnologia = aid["workflow_variables"].get("tecnologia", "")
    aid_tec_na = not bool(aid)
    aid_tec_ok = str(aid_tecnologia).strip().upper() == "AID" if aid else (not es_despliegue)
    resultado["validaciones"]["aid_tecnologia"] = {
        "ok": aid_tec_ok,
        "na": aid_tec_na and not es_despliegue,
        "tecnologia": aid_tecnologia,
        "detalle": f"{ICON_OK} tecnologia='AID'" if aid_tec_ok else f"{ICON_ERROR} tecnologia inválida: {aid_tecnologia or 'VACÍO'}"
    }

    # AID: TYPE debe ser "topic" en cada step, salvo excepciones conocidas
    # (ej. un step final que solo escribe/guarda resultados) — ver AID_TYPE_VALIDOS.
    aid_type_vals = []
    if aid:
        buscar_clave_todos(aid, "TYPE", aid_type_vals)
    aid_type = aid_type_vals[0] if aid_type_vals else ""

    aid_type_na = not bool(aid)
    aid_type_ok = all(str(t).strip().lower() in AID_TYPE_VALIDOS for t in aid_type_vals) if aid_type_vals else (not es_despliegue)
    resultado["validaciones"]["aid_type_topic"] = {
        "ok": aid_type_ok,
        "na": aid_type_na and not es_despliegue,
        "type": aid_type,
        "types": aid_type_vals,
        "detalle": f"{ICON_OK} TYPE válido" if aid_type_ok else f"{ICON_ERROR} TYPE inválido: {', '.join(str(t) for t in aid_type_vals) if aid_type_vals else 'VACÍO'}"
    }

    # Ambiente consistente entre AID (workflow_name) y UDZ (id)
    # ambiente
    amb = detectar_ambiente(aid_s3) if aid_s3 else "DESCONOCIDO"
    resultado["validaciones"]["ambiente"] = {
        "ambiente": amb,
        "s3_path": aid_s3
    }

    # coherencia nombres
    use_case = buscar_clave(aid, "use_case") or "" if aid else ""
    cu_name  = buscar_clave(ta,  "cu_name")  or "" if ta  else ""

    # Si falta use_case o cu_name y es MODIFICACIÓN → N/A
    coh_na = not (use_case and cu_name)
    if use_case and cu_name:
        nom_ok = use_case == cu_name
    else:
        nom_ok = not es_despliegue
    resultado["validaciones"]["coherencia"] = {
        "ok": nom_ok,
        "na": coh_na and not es_despliegue,
        "use_case": use_case,
        "cu_name": cu_name,
        "detalle": f"{ICON_OK} {use_case}" if nom_ok else f"{ICON_WARNING} AID use_case: {use_case} | TA cu_name: {cu_name}"
    }

    # criticos se calcula más abajo, después de out_zone_ok/copiar_ok

    #  VALIDACIONES ADICIONALES EN AID
    # LAST_STEP debe ser False (buscar todos los valores en la estructura)
    last_step_vals = []
    if aid:
        buscar_clave_todos(aid, "LAST_STEP", last_step_vals)

    # Validación: todos deben ser "False"
    ls_na = not bool(aid)
    last_step_ok = all(str(v).lower() == "false" for v in last_step_vals) if last_step_vals else (not es_despliegue)

    resultado["validaciones"]["last_step"] = {
        "ok": last_step_ok,
        "na": ls_na and not es_despliegue,
        "valores": last_step_vals,
        "encontrado": len(last_step_vals) > 0,
        "detalle": f"{ICON_OK} LAST_STEP en False" if last_step_ok else f"{ICON_ERROR} LAST_STEP: {last_step_vals}"
    }

    # out_zone y copiarResultadoBucket (validar por cada STEP_VARIABLES)
    # NOTA: SOLO si existe un step con FUNCTION_NAME = "call_api" Y tiene STEP_VARIABLES
    out_zones = []
    copiar_vals = []
    conflictos = []  # Almacena conflictos específicos
    tiene_call_api_con_step_vars = False

    if aid:
        # Primero: buscar si existe un step con "FUNCTION_NAME": "call_api" Y "STEP_VARIABLES"
        def buscar_call_api_con_step_vars(obj):
            if isinstance(obj, dict):
                # Si es un step con FUNCTION_NAME=call_api y tiene STEP_VARIABLES
                if (obj.get("FUNCTION_NAME", "").strip().lower() == "call_api" and
                    "STEP_VARIABLES" in obj):
                    return True
                # Buscar en valores anidados
                for v in obj.values():
                    if buscar_call_api_con_step_vars(v):
                        return True
            elif isinstance(obj, list):
                for item in obj:
                    if buscar_call_api_con_step_vars(item):
                        return True
            return False

        tiene_call_api_con_step_vars = buscar_call_api_con_step_vars(aid)

        # Función para buscar recursivamente y validar por STEP_VARIABLES
        def validar_step_vars(obj, path=""):
            if isinstance(obj, dict):
                # Si este objeto es un STEP_VARIABLES, validamos
                if "STEP_VARIABLES" in obj or ("copiarResultadoBucket" in obj and any(k in obj for k in ["out_zone", "use_case", "JOB_NAME"])):
                    sv = obj if "STEP_VARIABLES" not in obj else obj["STEP_VARIABLES"]
                    copiar = sv.get("copiarResultadoBucket", "")
                    out_z = sv.get("out_zone", "")

                    if copiar:
                        copiar_vals.append(copiar)
                    if out_z:
                        out_zones.append(out_z)

                    # Validar conflicto: si copiar=True pero existe out_zone
                    if str(copiar).lower() == "true" and out_z:
                        conflictos.append(f"copiarResultadoBucket=True con out_zone={out_z}")

                # Recursivo
                for k, v in obj.items():
                    validar_step_vars(v, path + f".{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    validar_step_vars(item, path + f"[{i}]")

        validar_step_vars(aid)

    # Reglas:
    # 1. Si copiarResultadoBucket=True y existe out_zone → ERROR (conflicto)
    # 2. Si existe out_zone pero NO existe copiarResultadoBucket → ERROR (falta setear copiar=True y quitar out_zone)
    # 3. Si no hay AID (MODIFICACIÓN sin AID) → N/A
    # 4. Si no hay call_api con STEP_VARIABLES → N/A (no aplica)
    if aid and tiene_call_api_con_step_vars:
        tiene_out_zone  = len(out_zones) > 0
        tiene_copiar    = len(copiar_vals) > 0
        copiar_es_true  = all(str(v).lower() == "true" for v in copiar_vals) if copiar_vals else False

        if tiene_out_zone and not tiene_copiar:
            # out_zone existe pero falta copiarResultadoBucket=True → error
            out_zone_ok = False
            copiar_ok   = False
        elif conflictos:
            # copiarResultadoBucket=True y out_zone coexisten → error
            out_zone_ok = False
            copiar_ok   = True
        elif tiene_copiar and not copiar_es_true:
            # copiarResultadoBucket existe pero no es True → error
            out_zone_ok = True
            copiar_ok   = False
        else:
            out_zone_ok = True
            copiar_ok   = True
    else:
        # Sin AID, sin call_api+STEP_VARIABLES, o MODIFICACIÓN → N/A, no bloquear
        out_zone_ok = not es_despliegue
        copiar_ok   = not es_despliegue

    oz_na = (not bool(aid)) or (not tiene_call_api_con_step_vars)
    resultado["validaciones"]["out_zone_copiar"] = {
        "out_zones": out_zones,
        "copiar_vals": copiar_vals,
        "conflictos": conflictos,
        "tiene_call_api_con_step_vars": tiene_call_api_con_step_vars,
        "na": oz_na,
        "out_zone_ok": out_zone_ok or oz_na,
        "copiar_ok": copiar_ok or oz_na,
        "detalle": f"{ICON_NA} No aplica (sin call_api+STEP_VARIABLES)" if oz_na else (f"{ICON_OK} Configuración correcta" if (out_zone_ok and copiar_ok) else f"{ICON_ERROR} Configuración incorrecta")
    }

    # Estado general — todas las validaciones críticas que NO son N/A deben estar ok
    criticos = [
        _val_ok(resultado["validaciones"].get(k, {}))
        for k in VALIDATION_KEYS
        if not resultado["validaciones"].get(k, {}).get("na", False)
    ]
    if incompleto_por_archivos:
        # DESPLIEGUE sin TA/AID/UDZ: aunque las validaciones individuales ya
        # quedaron marcadas como error (correctamente), el estado general es
        # INCOMPLETO, no ERROR — todavía no hay ni los archivos base.
        resultado["estado_code"] = ESTADO_INCOMPLETO
    else:
        resultado["estado_code"] = ESTADO_LISTO if all(criticos) else ESTADO_ERROR
    resultado["estado_general"] = estado_display(resultado["estado_code"])

    #  Trazabilidad: quién y cuándo se corrió este análisis
    resultado["analizado_por"] = obtener_usuario_actual()
    resultado["analizado_en"] = datetime.now().isoformat()

    # La confirmación de que se probó en QA es un acto explícito del usuario,
    # no algo que se recalcula solo. Si ya existía en el análisis guardado
    # previamente, se conserva al re-analizar (ya se leyó arriba en
    # _anterior, para no leer el archivo dos veces).
    if _anterior:
        campos_a_conservar = ["probado_qa_por", "probado_qa_en", "probado_qa_estado_code",
                               "rnf_copiado_por", "rnf_copiado_en"]
        # Trazabilidad de subida a AWS: igual, es un acto explícito por
        # componente (ta/aid/udz), se conserva al re-analizar. udz_crudos y
        # udz_resultados son los slots separados cuando la HU trae ambos
        # tipos de UDZ como archivos distintos (ver detectar_slots_udz).
        for _tipo_aws in ("ta", "aid", "udz", "udz_crudos", "udz_resultados"):
            campos_a_conservar += [f"{_tipo_aws}_aws_ambiente", f"{_tipo_aws}_aws_por",
                                    f"{_tipo_aws}_aws_en", f"{_tipo_aws}_aws_tabla"]
        for campo in campos_a_conservar:
            if _anterior.get(campo):
                resultado[campo] = _anterior[campo]

    # Guardar análisis
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")

    return resultado


def analizar_sprint(sprint_folder: Path) -> list:
    resultados = []
    for d in sorted(sprint_folder.iterdir()):
        if not d.is_dir():
            continue

        # Si no tiene metadata.json, crear uno mínimo automático
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            meta_auto = {
                "id": d.name[:10],
                "title": d.name,
                "state": "Manual",
                "work_item_type": "User Story",
                "iteration_path": "",
                "area_path": "",
                "created_date": "",
                "changed_date": "",
                "description": "",
                "tipo_cambio": "DESCONOCIDO",
                "downloaded_at": datetime.now().isoformat(),
                "attachments": []
            }
            meta_path.write_text(
                json.dumps(meta_auto, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )

        resultados.append(analizar_hu(d))

    return resultados
