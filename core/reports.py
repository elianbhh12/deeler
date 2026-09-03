"""Reportes: Excel consolidado del backlog y métricas de ciclo/efectividad.

Paleta alineada a la identidad del banco (mismos colores que usa la interfaz,
ver core/config.py) — deliberadamente sobria: acento amarillo + negro para
encabezados, y verde/rojo solo puntuales para marcar estado, sin pintar filas
enteras.
"""
from pathlib import Path
from io import BytesIO
from datetime import datetime
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .config import (
    ICON_OK, ICON_ERROR, ICON_WARNING, ICON_SUCCESS, ICON_FAIL,
    ACCENT, INK, GREEN, RED, MUTED,
)
from .analysis import get_estado_code, ESTADO_LISTO, ESTADO_ERROR, ESTADO_INCOMPLETO, ESTADO_SIN_METADATA

#  Colores del reporte — mismos que usa la app (sin el "#"), no un set aparte.
_C_ACCENT = ACCENT.lstrip("#")   # amarillo banco — fondo de encabezado
_C_INK    = INK.lstrip("#")      # negro — texto de encabezado y bordes
_C_GREEN  = GREEN.lstrip("#")    # éxito
_C_RED    = RED.lstrip("#")      # error
_C_MUTED  = MUTED.lstrip("#")    # texto secundario / N/A
_C_LINE   = "9C9A98"             # borde — gris oscuro, visible sin ser negro puro
_C_BANDA  = "FAFAF9"             # banda de fila alterna, muy sutil (= SURFACE de la UI)

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
    """Encabezado único y consistente para todas las hojas: fondo amarillo
    banco, texto negro — la misma combinación en Consolidado y Efectividad."""
    fill = PatternFill(start_color=_C_ACCENT, end_color=_C_ACCENT, fill_type="solid")
    for cell in ws[fila]:
        cell.fill = fill
        cell.font = _FONT_HEADER
        cell.alignment = _ALIGN_CENTRO
        cell.border = _BORDE
    ws.row_dimensions[fila].height = 20
    ws.freeze_panes = f"A{fila + 1}"
    ws.auto_filter.ref = f"A{fila}:{get_column_letter(ws.max_column)}{fila}"


def _autofit_columnas(ws, minimo=6, maximo=45, holgura=3):
    """Ajusta el ancho de cada columna al contenido más largo que tenga
    (encabezado o dato), con un margen para el ícono de autofiltro y sin
    dejar que una celda gigante desborde toda la hoja."""
    for columna in ws.columns:
        letra = get_column_letter(columna[0].column)
        largo = max((len(str(c.value)) for c in columna if c.value is not None), default=0)
        ws.column_dimensions[letra].width = max(minimo, min(maximo, largo + holgura))


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


def calcular_eficiencia_por_ciclo(created_date: str, downloaded_at: str, changed_date: str, estado_ado: str) -> tuple:
    """Calcula días de ciclo SOLO si estado_ado == 'Closed'
    Retorna (días_creación_a_cierre, días_descarga_a_cierre) o (0, 0) si aún está abierto"""
    if estado_ado != "Closed":
        return 0, 0

    try:
        fecha_creacion = datetime.fromisoformat(created_date.replace("Z", "+00:00"))
        fecha_descarga = datetime.fromisoformat(downloaded_at.replace("Z", "+00:00")) if downloaded_at else datetime.now()
        fecha_cierre   = datetime.fromisoformat(changed_date.replace("Z", "+00:00")) if changed_date else datetime.now()
        return (fecha_cierre - fecha_creacion).days, (fecha_cierre - fecha_descarga).days
    except:
        return 0, 0


def generar_excel_consolidado(resultados: list, guardar_en_carpeta: Path = None) -> bytes:
    """Genera Excel con Sprint, Estado ADO real, fechas de ciclo y métricas (solo para Closed)"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Consolidado"

    #  HEADERS
    headers = ["ID", "Título", "Tipo", "Sprint", "Estado ADO",
               "Fecha Creación", "Fecha Descarga", "Fecha Cierre",
               "Días Creación→Cierre", "Días Descarga→Cierre",
               "Probado en QA por", "Fecha prueba QA",
               "TA → AWS", "AID → AWS", "UDZ → AWS",
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
        estado_ado = r.get("estado_ado", "New")

        # Fechas reales de ADO
        created_date = r.get("created_date", "")
        downloaded_at = r.get("downloaded_at", "")
        changed_date = r.get("changed_date", "")

        # Parsear fechas para mostrar
        fecha_creacion = created_date[:10] if created_date else "?"
        fecha_descarga = downloaded_at[:10] if downloaded_at else "?"

        # Fecha de cierre: solo si está Closed
        if estado_ado == "Closed":
            fecha_cierre = changed_date[:10] if changed_date else "?"
        else:
            fecha_cierre = "-"  # Sin cerrar aún

        # Calcular ciclos (solo si está Closed)
        dias_creacion_cierre, dias_descarga_cierre = calcular_eficiencia_por_ciclo(
            created_date, downloaded_at, changed_date, estado_ado
        )

        # Si no está Closed, mostrar guiones en días
        dias_creacion_str = dias_creacion_cierre if dias_creacion_cierre > 0 else "-"
        dias_descarga_str = dias_descarga_cierre if dias_descarga_cierre > 0 else "-"

        # Trazabilidad de prueba en QA
        probado_qa_por = r.get("probado_qa_por") or "-"
        probado_qa_en_raw = r.get("probado_qa_en", "")
        probado_qa_en = probado_qa_en_raw[:16].replace("T", " ") if probado_qa_en_raw else "-"

        # Trazabilidad de subida a AWS, por componente — quién, a qué
        # ambiente y cuándo (ver ui/aws_console.py, que es quien la graba).
        # UDZ puede haberse subido como un solo archivo ("udz") o, si la HU
        # trae crudos y transmisión de resultados como archivos separados,
        # como dos partes independientes ("udz_crudos"/"udz_resultados",
        # ver core.analysis.detectar_slots_udz) — se muestran las que
        # existan, para no perder de vista que puede faltar una de las dos.
        _UDZ_ETIQUETA = {"udz_crudos": "Crudos", "udz_resultados": "Result."}

        def _aws_txt_una(clave):
            por = r.get(f"{clave}_aws_por")
            if not por:
                return None
            amb = (r.get(f"{clave}_aws_ambiente") or "").upper()
            en = (r.get(f"{clave}_aws_en") or "")[:16].replace("T", " ")
            _etq = _UDZ_ETIQUETA.get(clave)
            _pref = f"{_etq}: " if _etq else ""
            return f"{_pref}{amb} · {por} · {en}"

        def _aws_txt(tipo_comp):
            claves = [tipo_comp] if tipo_comp != "udz" else ["udz", "udz_crudos", "udz_resultados"]
            partes = [t for t in (_aws_txt_una(c) for c in claves) if t]
            return " | ".join(partes) if partes else "-"

        ta_aws = _aws_txt("ta")
        aid_aws = _aws_txt("aid")
        udz_aws = _aws_txt("udz")

        # Trazabilidad de despliegue real en PDN (hecho manual, posterior a
        # la prueba en QA — ver ui/hu_detail.py).
        desplegado_pdn_por = r.get("desplegado_pdn_por") or "-"
        desplegado_pdn_en_raw = r.get("desplegado_pdn_en", "")
        desplegado_pdn_en = desplegado_pdn_en_raw[:16].replace("T", " ") if desplegado_pdn_en_raw else "-"

        # Agregar fila con nuevas fechas (sin Ambiente)
        ws.append([
            hu_id, title, tipo, sprint, estado_ado,
            fecha_creacion, fecha_descarga, fecha_cierre,
            dias_creacion_str, dias_descarga_str,
            probado_qa_por, probado_qa_en,
            ta_aws, aid_aws, udz_aws,
            desplegado_pdn_por, desplegado_pdn_en
        ])

        # Aplicar estilos a fila: borde, centrado y una sola fuente en todo
        # el archivo — verde/rojo solo en los íconos ✓/✗, el resto en negro.
        for cell in ws[row]:
            cell.border = _BORDE
            cell.alignment = _ALIGN_CENTRO
            if ICON_SUCCESS in str(cell.value):
                cell.font = Font(name=_FUENTE, color=_C_GREEN)
            elif ICON_FAIL in str(cell.value):
                cell.font = Font(name=_FUENTE, color=_C_RED)
            else:
                cell.font = _FONT_DATA

        row += 1

    _bandear_filas(ws, 2, row - 1)

    #  AJUSTAR ANCHO COLUMNAS al contenido real (encabezado o dato más largo
    #  de cada columna), no a un valor fijo — así si cambia el texto de un
    #  encabezado o el largo típico de un dato, la celda se sigue viendo
    #  completa sin volver a tocar este número a mano.
    _autofit_columnas(ws)

    #  HOJA: EFECTIVIDAD
    ws_ef = wb.create_sheet("Efectividad")

    # Agrupar resultados por sprint
    sprints_data = defaultdict(list)
    for r in resultados:
        sprints_data[r.get("sprint", "Sin Sprint")].append(r)

    ef_headers = [
        "Sprint", "Total HU", f"{ICON_OK} Listos", f"{ICON_ERROR} Con Errores", f"{ICON_WARNING} Incompletos",
        "% éxito", "Errores en TA", "Errores en AID", "Errores en UDZ",
        "DESPLIEGUE", "MODIFICACIÓN", "Subido a AWS", "Fecha Análisis"
    ]
    ws_ef.append(ef_headers)
    _header_style(ws_ef)

    ef_row = 2
    for sprint_name, hu_list in sorted(sprints_data.items()):
        total      = len(hu_list)
        listos     = sum(1 for r in hu_list if get_estado_code(r) == ESTADO_LISTO)
        errores    = sum(1 for r in hu_list if get_estado_code(r) == ESTADO_ERROR)
        incompl    = sum(1 for r in hu_list if get_estado_code(r) in (ESTADO_INCOMPLETO, ESTADO_SIN_METADATA))
        pct        = f"{round(listos / total * 100)}%" if total else "0%"

        # Errores por componente: cualquier validación que depende de ese archivo y falló
        err_ta = err_aid = err_udz = 0
        for r in hu_list:
            v = r.get("validaciones", {})
            arcs = r.get("archivos", {})
            if "NO" not in arcs.get("TA", "NO"):
                if not v.get("kafka", {}).get("ok", True) or not v.get("coherencia", {}).get("ok", True):
                    err_ta += 1
            if "NO" not in arcs.get("AID", "NO"):
                if not v.get("s3_path", {}).get("ok", True) or not v.get("last_step", {}).get("ok", True) or not v.get("out_zone_copiar", {}).get("out_zone_ok", True):
                    err_aid += 1
            if "NO" not in arcs.get("UDZ", "NO"):
                if not v.get("s3_path", {}).get("ok", True) or not v.get("workflow_vs_id", {}).get("ok", True):
                    err_udz += 1

        desp = sum(1 for r in hu_list if "DESP" in r.get("tipo_cambio", "").upper())
        modi = sum(1 for r in hu_list if "MODI" in r.get("tipo_cambio", "").upper())

        # Eficiencia de despliegue real: cuántas HU del sprint tuvieron al
        # menos un componente efectivamente subido a AWS (no solo validado).
        subidas_aws = sum(
            1 for r in hu_list
            if any(r.get(f"{t}_aws_por") for t in ("ta", "aid", "udz"))
        )

        # Fecha del análisis más reciente del sprint
        fechas = [r.get("downloaded_at", "")[:10] for r in hu_list if r.get("downloaded_at")]
        fecha_analisis = max(fechas) if fechas else datetime.now().strftime("%Y-%m-%d")

        ws_ef.append([sprint_name, total, listos, errores, incompl, pct,
                       err_ta, err_aid, err_udz, desp, modi, subidas_aws, fecha_analisis])

        # Sin pintar la fila entera (muy cargado visualmente) — solo un
        # indicador puntual de color en la celda de "% éxito". Misma fuente
        # y centrado que el resto del archivo.
        pct_color = _C_GREEN if listos == total else (_C_RED if errores >= total - listos else "B45309")
        for cell in ws_ef[ef_row]:
            cell.border = _BORDE
            cell.alignment = _ALIGN_CENTRO
            cell.font = _FONT_DATA
        ws_ef.cell(row=ef_row, column=6).font = Font(name=_FUENTE, bold=True, color=pct_color)
        ef_row += 1

    _bandear_filas(ws_ef, 2, ef_row - 1)

    _autofit_columnas(ws_ef)

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
