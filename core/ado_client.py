"""Todo lo que habla con Azure DevOps: construir URLs y traer HU nuevas."""
import re
import json
import time
import zipfile
from pathlib import Path
from datetime import datetime

import requests
import streamlit as st

from .config import ORG, PROJECT, TEAM, AREA, HEADERS, ROOT_FOLDER, DEALER_NAME, MI_INFO, MI_OK, MI_WARNING, MI_ERROR
from .utils import safe_name


def ado_url(path, use_team=False):
    if use_team:
        return f"https://dev.azure.com/{ORG}/{PROJECT}/{TEAM}/_apis/{path}"
    return f"https://dev.azure.com/{ORG}/{PROJECT}/_apis/{path}"


def _get_con_reintentos(url, headers, timeout=60, intentos=3, espera=1.5):
    """GET con reintentos ante fallas transitorias de red (DNS, conexión
    reseteada, timeout) — típico de una VPN corporativa bajo carga cuando se
    hacen muchas descargas seguidas rápido: falla con algunos adjuntos, no
    con todos, y el siguiente intento normalmente sí resuelve. No reintenta
    errores HTTP reales (401/403/404) porque esos no se arreglan solos."""
    for intento in range(1, intentos + 1):
        try:
            return requests.get(url, headers=headers, timeout=timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if intento >= intentos:
                raise
            time.sleep(espera)
    raise RuntimeError("_get_con_reintentos: intentos debe ser >= 1")


def descargar_hu(iteration_path: str):
    log_container = st.empty()

    def log_info(m):
        log_container.info(m, icon=MI_INFO)
    def log_success(m):
        log_container.success(m, icon=MI_OK)
    def log_warning(m):
        log_container.warning(m, icon=MI_WARNING)
    def log_error(m):
        log_container.error(m, icon=MI_ERROR)

    log_info(f"Consultando HU en: {iteration_path}")

    # Filtro AssignedTo: sin asignar O asignado al dealer
    dealer = DEALER_NAME
    if dealer:
        assigned_filter = f"AND ([System.AssignedTo] = '' OR [System.AssignedTo] = '{dealer}')"
    else:
        assigned_filter = "AND [System.AssignedTo] = ''"

    wiql = {
        "query": f"""
        SELECT [System.Id], [System.Title], [System.AssignedTo], [System.AreaPath]
        FROM WorkItems
        WHERE [System.TeamProject] = @project
          AND [System.WorkItemType] IN ('User Story', 'Issue')
          AND [System.State] <> 'Closed'
          AND [System.IterationPath] = '{iteration_path}'
          AND [System.AreaPath] UNDER '{AREA}'
          AND [System.Title] CONTAINS 'PIA'
          {assigned_filter}
        ORDER BY [System.ChangedDate] DESC
        """
    }
    try:
        r = requests.post(ado_url("wit/wiql?api-version=7.1", use_team=True),
                          headers=HEADERS, json=wiql, timeout=30)
        r.raise_for_status()
        ids = [w["id"] for w in r.json().get("workItems", [])]
        log_success(f"Encontrados {len(ids)} items con PIA")
    except Exception as e:
        log_error(f"Error consultando: {e}")
        return 0

    if not ids:
        log_warning("No hay HU con PIA en este sprint")
        return 0

    ids_csv = ",".join(map(str, ids))
    try:
        r = _get_con_reintentos(
            ado_url(f"wit/workitems?ids={ids_csv}&$expand=relations&api-version=7.1"),
            headers=HEADERS, timeout=30)
        r.raise_for_status()
        items = r.json().get("value", [])
    except Exception as e:
        log_error(f"Error descargando detalles: {e}")
        return 0

    # La carpeta del sprint es solo el último segmento del iteration_path
    # (ej. "Sprint 252"), no el área completa — más corto (deja margen para
    # el límite de 260 caracteres de Windows), más legible, y el nombre
    # completo de cada HU ya va en su propia carpeta adentro.
    _partes_iter = [p for p in iteration_path.split("\\") if p]
    _nombre_sprint_folder = safe_name(_partes_iter[-1]) if _partes_iter else "sprint"
    sprint_folder = Path(ROOT_FOLDER) / _nombre_sprint_folder
    sprint_folder.mkdir(parents=True, exist_ok=True)

    # IDs ya descargados — evitar re-descarga
    ids_existentes = set()
    if sprint_folder.exists():
        for d in sprint_folder.iterdir():
            if d.is_dir():
                m = re.match(r"^(\d+)-", d.name)
                if m:
                    ids_existentes.add(int(m.group(1)))

    nuevos = [wi for wi in items if wi["id"] not in ids_existentes]
    ya_existentes = len(items) - len(nuevos)

    if ya_existentes:
        log_info(f"{ya_existentes} HU ya descargadas — omitidas")
    if not nuevos:
        log_success("Todo está al día, no hay HU nuevas")
        return 0

    # Barra de progreso
    progress_bar = st.progress(0)
    status_text  = st.empty()

    # Cuánto título de HU entra sin pasarse del límite de 260 caracteres de
    # Windows: se calcula según el ROOT_FOLDER real (no un número fijo
    # adivinado) — así en un ROOT_FOLDER corto el título sale casi completo,
    # y solo se recorta lo justo y necesario cuando el ROOT_FOLDER es largo.
    # El título importa para poder identificar la HU a simple vista en el
    # Explorador, así que la reserva para el adjunto usa un largo realista
    # (~85, los nombres reales rondan 60-70) en vez del máximo teórico (120,
    # el límite que sigue permitiendo safe_name para adjuntos) — en el caso
    # raro de un adjunto excepcionalmente largo, cargar_json ya avisa con un
    # mensaje claro en vez de romper (ver core/analysis.py), así que vale la
    # pena priorizar el título en el caso común.
    _margen_archivo = 10 + 85 + 10  # "\adjuntos\" + nombre de archivo + "wid-"
    _max_len_titulo = max(30, min(120, 260 - len(str(sprint_folder)) - _margen_archivo))

    sin_asignar = []  # HU sin asignar para notificar al final
    errores_zip = []  # ZIPs que no se pudieron descomprimir — el log_container
                       # es compartido y se pisa entre attachments, así que
                       # esto se junta acá para mostrarlo persistente al final
    errores_descarga = []  # adjuntos que fallaron al bajar (con el motivo real)

    for idx, wi in enumerate(nuevos, 1):
        wid       = wi["id"]
        f         = wi.get("fields", {})
        title     = f.get("System.Title", "sin titulo")
        asignado  = f.get("System.AssignedTo", {})
        asignado  = asignado.get("displayName", "") if isinstance(asignado, dict) else str(asignado or "")

        if not asignado:
            sin_asignar.append(f"HU {wid}: {title[:50]}")

        # Actualizar progreso
        progress_bar.progress(idx / len(nuevos))
        status_text.info(f"Descargando {idx}/{len(nuevos)}: {title[:50]}...")

        hu_folder  = sprint_folder / f"{wid}-{safe_name(title, _max_len_titulo)}"
        adj_folder = hu_folder / "adjuntos"
        for p in [hu_folder, adj_folder, hu_folder/"analisis", hu_folder/"evidencia"]:
            p.mkdir(parents=True, exist_ok=True)

        # Detectar tipo de cambio: MODIFICACIÓN o DESPLIEGUE
        desc = (f.get("System.Description") or "").lower()
        if "modificación" in desc or "modificacion" in desc:
            # Buscar respuesta: "True" = MODIFICACIÓN, "False" = DESPLIEGUE
            if "true" in desc:
                tipo_cambio = "MODIFICACIÓN"
            elif "false" in desc:
                tipo_cambio = "DESPLIEGUE"
            # Fallback: buscar "sí"/"si" para casos con texto en español
            elif "sí" in desc or "si" in desc or "yes" in desc:
                tipo_cambio = "MODIFICACIÓN"
            else:
                tipo_cambio = "DESPLIEGUE"
        else:
            tipo_cambio = "DESCONOCIDO"

        metadata = {
            "id": wid, "title": title,
            "state": f.get("System.State", ""),
            "assigned_to": asignado,
            "work_item_type": f.get("System.WorkItemType", ""),
            "iteration_path": iteration_path,
            "area_path": f.get("System.AreaPath", ""),
            "created_date": f.get("System.CreatedDate", ""),
            "changed_date": f.get("System.ChangedDate", ""),
            "description": (f.get("System.Description") or "")[:500],
            "tipo_cambio": tipo_cambio,
            "downloaded_at": datetime.now().isoformat(),
            "attachments": []
        }

        for rel in (wi.get("relations") or []):
            if rel.get("rel") == "AttachedFile":
                url  = rel["url"]
                name = rel.get("attributes", {}).get("name", "adjunto.bin")

                # Metadata "fantasma" de macOS (resource fork "._nombre" o
                # ".DS_Store") — pasa también cuando se adjuntan archivos
                # sueltos (no en un .zip) desde Mac, no solo dentro de un ZIP.
                # Se descarta antes de gastar la descarga.
                if name.startswith("._") or name == ".DS_Store":
                    log_info(f"Ignorado (metadata de macOS): {name}")
                    continue

                out  = adj_folder / safe_name(name, 120)
                try:
                    resp = _get_con_reintentos(url, headers=HEADERS, timeout=60)
                    resp.raise_for_status()
                    out.write_bytes(resp.content)
                    metadata["attachments"].append({"name": name, "downloaded": True})
                    log_info(name)

                    #  Descomprimir ZIP automáticamente
                    if out.suffix.lower() == ".zip":
                        try:
                            with zipfile.ZipFile(out, "r") as zf:
                                for member in zf.namelist():
                                    if member.endswith("/"):
                                        continue  # entrada de carpeta, no un archivo
                                    nombre_miembro = Path(member).name
                                    # ZIPs armados en Mac traen, por cada archivo real, una
                                    # copia "fantasma" con metadata (resource fork) dentro de
                                    # __MACOSX/ y con el nombre prefijado "._" — nunca es
                                    # contenido real, se descarta siempre.
                                    if "__MACOSX" in Path(member).parts or nombre_miembro.startswith("._") or nombre_miembro == ".DS_Store":
                                        continue
                                    # Se extrae CUALQUIER archivo real (json, xlsx del RNF,
                                    # eml, etc.) — antes había una lista fija de extensiones
                                    # permitidas y todo lo demás se perdía en silencio (el
                                    # ZIP original se borra después de extraer).
                                    target = adj_folder / safe_name(nombre_miembro, 120)
                                    target.write_bytes(zf.read(member))
                                    log_info(f"Extraído: {nombre_miembro}")
                            out.unlink()  # eliminar el ZIP original
                        except Exception as ze:
                            log_warning(f"No se pudo descomprimir {name}: {ze}")
                            errores_zip.append(f"HU {wid} — {name}: {ze}")

                except Exception as ex:
                    metadata["attachments"].append({"name": name, "downloaded": False, "error": str(ex)})
                    log_warning(f"Error descargando {name}: {ex}")
                    errores_descarga.append(f"HU {wid} — {name}: {ex}")

        (hu_folder / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        (hu_folder / "resumen.md").write_text(
            f"# {metadata['work_item_type']} {wid}\n\n**Título:** {title}\n\n"
            f"**Tipo:** {metadata['tipo_cambio']}\n\n"
            f"**Asignado:** {asignado or 'Sin asignar'}\n\n"
            f"**Estado:** {metadata['state']}\n\n**Sprint:** {iteration_path}\n\n"
            f"**Adjuntos:** {len(metadata['attachments'])}\n", encoding="utf-8")

        log_success(f"HU {wid} procesada: {title[:50]}")

    # Limpiar y mostrar resumen
    progress_bar.empty()
    status_text.empty()
    log_success(f"Descarga completada: {len(nuevos)} HU nuevas procesadas")

    #  Alerta de HU sin asignar
    if sin_asignar:
        st.warning(
            f"**{len(sin_asignar)} HU sin asignar** — revísalas y asígnalas en ADO:\n\n" +
            "\n".join(f"- {hu}" for hu in sin_asignar),
            icon=MI_WARNING,
        )

    #  Alerta de ZIPs que no se pudieron descomprimir — sin esto, un adjunto
    #  que falla queda con el TA/AID/UDZ faltante y sin explicación visible,
    #  porque el aviso de arriba (log_warning) se pisa con el siguiente log.
    if errores_zip:
        st.error(
            f"**{len(errores_zip)} adjunto(s) no se pudieron descomprimir** — esa HU va a quedar "
            f"sin ese componente hasta que se resuelva (volvé a adjuntar el archivo sin comprimir, "
            f"o revisá que el ZIP no esté corrupto):\n\n" +
            "\n".join(f"- {e}" for e in errores_zip),
            icon=MI_ERROR,
        )

    #  Alerta de adjuntos que fallaron al descargarse (con el motivo real de
    #  requests — timeout, 404, permisos, etc.), mismo problema de log que se
    #  pisa: antes esto solo decía "Error: nombre.zip" sin explicar por qué.
    if errores_descarga:
        st.error(
            f"**{len(errores_descarga)} adjunto(s) no se pudieron descargar:**\n\n" +
            "\n".join(f"- {e}" for e in errores_descarga),
            icon=MI_ERROR,
        )

    return len(nuevos)
