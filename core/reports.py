"""Reportes: Excel consolidado del backlog (hoja única).

Paleta alineada a la identidad del banco (mismos colores que usa la interfaz,
ver core/config.py) — deliberadamente sobria: acento amarillo + negro para
encabezados, y verde/rojo solo puntuales para marcar estado, sin pintar filas
enteras (salvo el resaltado de HU ya desplegadas en PDN).
"""
from pathlib import Path
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

import json

from .config import ICON_SUCCESS, ICON_FAIL, ACCENT, INK, GREEN, RED, MUTED
from .analysis import obtener_estado_pdn_real

#  Colores del reporte — mismos que usa la app (sin el "#"), no un set aparte.
_C_ACCENT = ACCENT.lstrip("#")   # amarillo banco — fondo de encabezado
_C_INK    = INK.lstrip("#")      # negro — texto de encabezado y bordes
_C_GREEN  = GREEN.lstrip("#")    # éxito
_C_RED    = RED.lstrip("#")      # error
_C_MUTED  = MUTED.lstrip("#")    # texto secundario / N/A
_C_LINE   = "9C9A98"             # borde — gris oscuro, visible sin ser negro puro
_C_BANDA  = "FAFAF9"             # banda de fila alterna, muy sutil (= SURFACE de la UI)

_C_PDN_BG = "D1FAE5"              # verde claro — mismo tono que usa la UI para "ok"

_FUENTE = "Calibri"               # una sola fuente en todo el archivo
_FONT_HEADER = Font(name=_FUENTE, bold=True, color=_C_INK)
_FONT_DATA   = Font(name=_FUENTE, color=_C_INK)
_ALIGN_CENTRO = Alignment(horizontal="center", vertical="center")
_BORDE = Border(
    left=Side(style="thin", color=_C_LINE),
    right=Side(style="thin", color=_C_LINE),
    top=Side(style="thin", color=_C_LINE),
    bottom=Side(style="thin", color=_C_LINE),
)


def _header_style(ws, fila=1):
    """Encabezado único y consistente: fondo amarillo banco, texto negro."""
    fill = PatternFill(start_color=_C_ACCENT, end_color=_C_ACCENT, fill_type="solid")
    for cell in ws[fila]:
        cell.fill = fill
        cell.font = _FONT_HEADER
        cell.alignment = _ALIGN_CENTRO
        cell.border = _BORDE
    ws.row_dimensions[fila].height = 20
    ws.freeze_panes = f"A{fila + 1}"
    ws.auto_filter.ref = f"A{fila}:{get_column_letter(ws.max_column)}{fila}"


def _autofit_columnas(ws, minimo=6, maximo=45, holgura=3, maximos_por_encabezado=None):
    """Ajusta el ancho de cada columna al contenido más largo que tenga
    (encabezado o dato), con un margen para el ícono de autofiltro y sin
    dejar que una celda gigante desborde toda la hoja. `maximos_por_encabezado`
    permite un tope más alto para columnas puntuales con contenido largo
    (ej. rutas S3), en vez de recortarlas todas al mismo `maximo` general."""
    maximos_por_encabezado = maximos_por_encabezado or {}
    for columna in ws.columns:
        letra = get_column_letter(columna[0].column)
        largo = max((len(str(c.value)) for c in columna if c.value is not None), default=0)
        encabezado = columna[0].value
        tope = maximos_por_encabezado.get(encabezado, maximo)
        ws.column_dimensions[letra].width = max(minimo, min(tope, largo + holgura))


def _bandear_filas(ws, primera_fila_datos, ultima_fila):
    """Pinta filas alternas con una banda muy sutil para que se vea como una
    tabla real, sin tocar bordes/fuente/alineación (eso ya lo puso cada fila
    al construirse) y sin pisar celdas que ya tengan un color propio (los
    íconos ✓/✗ o el % de éxito)."""
    banda_fill = PatternFill(start_color=_C_BANDA, end_color=_C_BANDA, fill_type="solid")
    for fila in range(primera_fila_datos, ultima_fila + 1):
        if (fila - primera_fila_datos) % 2 == 0:
            continue
        for cell in ws[fila]:
            if cell.fill.fgColor.rgb in (None, "00000000"):
                cell.fill = banda_fill


def _nombre_archivo(r: dict, clave: str) -> str:
    """Nombre del archivo TA/AID activo de esta HU, leído directo del path
    guardado en r["{ta|aid}_activo"] (no del análisis guardado en
    analisis_tecnico.json) — "-" si no hay archivo activo para esa clave."""
    campo = f"{clave.lower()}_activo"
    val = r.get(campo)
    return Path(val).name if val else "-"


def _leer_aid_activo(r: dict):
    """Lee el AID activo de esta HU directo del disco (no lo que quedó
    guardado en analisis_tecnico.json en el último análisis) — así las
    columnas que dependen de esto siempre reflejan el archivo actual, no
    hace falta re-analizar la HU para que el Excel se entere de un cambio.
    Lectura silenciosa (sin avisos en la UI): esto corre para cada fila de
    un reporte en segundo plano, no tiene sentido un warning por archivo.
    Devuelve el dict del AID, o None si no hay archivo o no se pudo leer."""
    aid_path = r.get("aid_activo")
    if not aid_path:
        return None
    try:
        aid_data = json.loads(Path(aid_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    return aid_data if isinstance(aid_data, dict) else None


def _s3_path_aid(r: dict) -> str:
    """s3_path declarado en el AID de esta HU — "-" si no hay AID, no se
    pudo leer, o no tiene el campo."""
    aid_data = _leer_aid_activo(r)
    val = aid_data.get("s3_path", "") if aid_data else ""
    return val if val else "-"


def _nombre_subtipo_aid(r: dict) -> str:
    """workflow_variables.tipoDocumento del AID de esta HU — "-" si no hay
    AID, no se pudo leer, o no tiene el campo."""
    aid_data = _leer_aid_activo(r)
    wf_vars = aid_data.get("workflow_variables") if aid_data else None
    val = wf_vars.get("tipoDocumento", "") if isinstance(wf_vars, dict) else ""
    return val if val else "-"


def _leer_udz_activo(r: dict):
    """Lee el UDZ activo de esta HU directo del disco, igual que
    _leer_aid_activo — algunos UDZ envuelven sus campos en un objeto
    "item", así que se devuelve ya "desenvuelto"."""
    udz_path = r.get("udz_activo")
    if not udz_path:
        return None
    try:
        udz_data = json.loads(Path(udz_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(udz_data, dict):
        return None
    item = udz_data.get("item")
    return item if isinstance(item, dict) else udz_data


def _udz_necesita_transmision(r: dict) -> str:
    """Sí/No según require_transmission del UDZ activo, leído del archivo
    actual en disco — "-" si no hay UDZ o no se pudo determinar."""
    udz_data = _leer_udz_activo(r)
    val = str(udz_data.get("require_transmission", "")).strip().lower() if udz_data else ""
    if val == "true":
        return "Sí"
    if val == "false":
        return "No"
    return "-"


def generar_excel_consolidado(resultados: list, guardar_en_carpeta: Path = None, cargas_directas: list = None) -> bytes:
    """Genera el Excel Consolidado: ID/título/tipo/sprint, el registro de
    qué TA/AID se subió (nombre de archivo, S3 Path, subtipo), si el UDZ
    necesita transmisión, y el despliegue real en PDN (resaltado en verde).
    El estado de QA se muestra en la tabla de Streamlit (ui/backlog.py), no
    en este Excel. Si se pasan `cargas_directas` (el log de "Carga directa"
    sin HU), se agregan en una segunda hoja del mismo libro."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Consolidado"

    #  HEADERS
    headers = ["ID", "Título", "Tipo", "Sprint",
               "TA", "AID Configuracion", "Nombre de Subtipo", "S3 Path", "Transmisiones",
               "Desplegado en PDN por", "Fecha despliegue PDN"]

    ws.append(headers)
    _header_style(ws)

    #  DATOS
    row = 2
    for r in sorted(resultados, key=lambda x: x.get("downloaded_at", ""), reverse=True):
        hu_id = r.get("hu_id", "")
        title = r.get("hu_title", "")[:50]
        tipo = r.get("tipo_cambio", "")
        sprint = r.get("sprint", "?")

        _pdn_real = obtener_estado_pdn_real(r)
        desplegado_pdn_por = _pdn_real["por"] or "-"
        desplegado_pdn_en_raw = _pdn_real["en"] or ""
        desplegado_pdn_en = desplegado_pdn_en_raw[:16].replace("T", " ") if desplegado_pdn_en_raw else "-"

        ws.append([
            hu_id, title, tipo, sprint,
            _nombre_archivo(r, "TA"), _nombre_archivo(r, "AID"), _nombre_subtipo_aid(r),
            _s3_path_aid(r), _udz_necesita_transmision(r),
            desplegado_pdn_por, desplegado_pdn_en
        ])

        # Una HU ya desplegada en PDN se resalta entera en verde claro.
        _fill_pdn = PatternFill(start_color=_C_PDN_BG, end_color=_C_PDN_BG, fill_type="solid") if _pdn_real["desplegado"] else None
        for cell in ws[row]:
            cell.border = _BORDE
            cell.alignment = _ALIGN_CENTRO
            if ICON_SUCCESS in str(cell.value):
                cell.font = Font(name=_FUENTE, color=_C_GREEN)
            elif ICON_FAIL in str(cell.value):
                cell.font = Font(name=_FUENTE, color=_C_RED)
            else:
                cell.font = _FONT_DATA
            if _fill_pdn:
                cell.fill = _fill_pdn

        row += 1

    _bandear_filas(ws, 2, row - 1)

    _autofit_columnas(ws, maximos_por_encabezado={"S3 Path": 90})

    if cargas_directas:
        _agregar_hoja_cargas_directas(wb, cargas_directas)

    # Guardar a bytes
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    # Si se proporciona una carpeta, guardar también allí con nombre estándar
    if guardar_en_carpeta:
        guardar_en_carpeta.mkdir(parents=True, exist_ok=True)
        archivo_path = guardar_en_carpeta / "Consolidado_Backlog.xlsx"
        wb.save(str(archivo_path))

    return output.getvalue()


def _agregar_hoja_cargas_directas(wb: Workbook, cargas_directas: list):
    """Segunda hoja del mismo libro con el registro de "Carga directa" (sin
    HU) — mismo formato que core.aws_upload/_registrar_carga_directa en
    ui/aws_console.py: una fila por componente subido, con el nombre de
    archivo (TA/AID) o si necesitaba transmisión (UDZ)."""
    ws2 = wb.create_sheet("Cargas Directas")
    headers = ["Fecha", "Flujo / Referencia", "Componente", "Archivo",
               "Transmisiones", "Ambiente", "Tabla", "Subido por", "Resultado"]
    ws2.append(headers)
    _header_style(ws2)

    row = 2
    for reg in sorted(cargas_directas, key=lambda x: x.get("en", ""), reverse=True):
        tipo = str(reg.get("tipo", "")).lower()
        transmision = reg.get("transmision", "-") if tipo == "udz" else "-"
        fecha = (reg.get("en") or "")[:16].replace("T", " ") or "-"
        resultado_txt = f"{ICON_SUCCESS} OK" if reg.get("ok") else f"{ICON_FAIL} Error"
        ws2.append([
            fecha, reg.get("referencia", "-") or "-", tipo.upper(),
            reg.get("archivo_original", "-"), transmision,
            str(reg.get("ambiente", "")).upper(), reg.get("tabla", "-"),
            reg.get("por", "-"), resultado_txt,
        ])
        for cell in ws2[row]:
            cell.border = _BORDE
            cell.alignment = _ALIGN_CENTRO
            if ICON_SUCCESS in str(cell.value):
                cell.font = Font(name=_FUENTE, color=_C_GREEN)
            elif ICON_FAIL in str(cell.value):
                cell.font = Font(name=_FUENTE, color=_C_RED)
            else:
                cell.font = _FONT_DATA
        row += 1

    _bandear_filas(ws2, 2, row - 1)
    _autofit_columnas(ws2)
