import json
from io import BytesIO

from openpyxl import load_workbook

import core.reports as reports


def _resultado_base(**overrides):
    base = {
        "hu_id": 1001, "hu_title": "HU de prueba", "tipo_cambio": "DESPLIEGUE",
        "sprint": "Sprint 253", "estado_ado": "Active",
        "created_date": "2026-01-01T00:00:00Z", "changed_date": "2026-01-02T00:00:00Z",
        "downloaded_at": "2026-01-01T00:00:00",
    }
    base.update(overrides)
    return base


def _escribir_json(tmp_path, nombre, **campos):
    path = tmp_path / nombre
    path.write_text(json.dumps(campos), encoding="utf-8")
    return str(path)


def _escribir_aid(tmp_path, **campos_aid):
    return _escribir_json(tmp_path, "aid_x.json", **campos_aid)


def _escribir_udz(tmp_path, **campos_udz):
    return _escribir_json(tmp_path, "udz_x.json", **campos_udz)


def test_consolidado_incluye_nombre_de_archivo_ta_y_aid(tmp_path):
    ta_activo = _escribir_json(tmp_path, "ta_pia_demo.json", texto="x")
    aid_activo = _escribir_aid(tmp_path)
    resultados = [_resultado_base(ta_activo=ta_activo, aid_activo=aid_activo)]
    contenido = reports.generar_excel_consolidado(resultados)
    wb = load_workbook(BytesIO(contenido))
    ws = wb["Consolidado"]
    headers = [c.value for c in ws[1]]
    assert "TA" in headers
    assert "AID Configuracion" in headers
    assert "S3 Path" in headers
    assert "Transmisiones" in headers
    assert "Estado ADO" not in headers
    assert "Fecha Creación" not in headers
    assert "Fecha Cierre" not in headers

    fila = {headers[i]: c.value for i, c in enumerate(ws[2])}
    assert fila["TA"] == "ta_pia_demo.json"
    assert fila["AID Configuracion"] == "aid_x.json"


def test_consolidado_nombre_de_subtipo_desde_workflow_variables(tmp_path):
    aid_activo = _escribir_aid(tmp_path, workflow_variables={"tecnologia": "AID", "tipoDocumento": "Seguro de activo"})
    resultados = [_resultado_base(aid_activo=aid_activo)]
    contenido = reports.generar_excel_consolidado(resultados)
    wb = load_workbook(BytesIO(contenido))
    ws = wb["Consolidado"]
    headers = [c.value for c in ws[1]]
    assert "Nombre de Subtipo" in headers
    fila = {headers[i]: c.value for i, c in enumerate(ws[2])}
    assert fila["Nombre de Subtipo"] == "Seguro de activo"


def test_consolidado_nombre_de_subtipo_sin_aid_muestra_guion():
    resultados = [_resultado_base()]  # sin "aid_activo"
    contenido = reports.generar_excel_consolidado(resultados)
    wb = load_workbook(BytesIO(contenido))
    ws = wb["Consolidado"]
    headers = [c.value for c in ws[1]]
    fila = {headers[i]: c.value for i, c in enumerate(ws[2])}
    assert fila["Nombre de Subtipo"] == "-"


#  TA, AID Configuracion, S3 Path, Nombre de Subtipo y Transmisiones se leen
#  todas del archivo real en disco (no del análisis guardado en
#  analisis_tecnico.json) — así el Excel siempre refleja el contenido actual
#  del archivo, sin tener que re-analizar la HU primero cada vez que alguien
#  edita el TA/AID/UDZ.

def test_consolidado_s3_path_desde_archivo_real(tmp_path):
    aid_activo = _escribir_aid(tmp_path, s3_path="s3://bucket-pdn-demo/resultados")
    resultados = [_resultado_base(aid_activo=aid_activo)]
    contenido = reports.generar_excel_consolidado(resultados)
    wb = load_workbook(BytesIO(contenido))
    ws = wb["Consolidado"]
    headers = [c.value for c in ws[1]]
    fila = {headers[i]: c.value for i, c in enumerate(ws[2])}
    assert fila["S3 Path"] == "s3://bucket-pdn-demo/resultados"


def test_consolidado_s3_path_refleja_el_archivo_actual_sin_reanalizar(tmp_path):
    """Si se edita el AID en disco (ej. se corrige el s3_path) y se regenera
    el Excel sin re-analizar la HU, debe verse el valor nuevo — no el que
    haya quedado guardado en un análisis previo."""
    aid_activo = _escribir_aid(tmp_path, s3_path="s3://bucket-viejo/algo")
    resultados = [_resultado_base(aid_activo=aid_activo)]

    # Se "edita" el archivo después de la primera vez que se generó el Excel.
    with open(aid_activo, "w", encoding="utf-8") as f:
        json.dump({"s3_path": "s3://bucket-nuevo/algo"}, f)

    contenido = reports.generar_excel_consolidado(resultados)
    wb = load_workbook(BytesIO(contenido))
    ws = wb["Consolidado"]
    headers = [c.value for c in ws[1]]
    fila = {headers[i]: c.value for i, c in enumerate(ws[2])}
    assert fila["S3 Path"] == "s3://bucket-nuevo/algo"


def test_consolidado_s3_path_sin_aid_muestra_guion():
    resultados = [_resultado_base()]  # sin "aid_activo"
    contenido = reports.generar_excel_consolidado(resultados)
    wb = load_workbook(BytesIO(contenido))
    ws = wb["Consolidado"]
    headers = [c.value for c in ws[1]]
    fila = {headers[i]: c.value for i, c in enumerate(ws[2])}
    assert fila["S3 Path"] == "-"


def test_consolidado_udz_necesita_transmision(tmp_path):
    udz_activo = _escribir_udz(tmp_path, require_transmission="true")
    resultados = [_resultado_base(udz_activo=udz_activo)]
    contenido = reports.generar_excel_consolidado(resultados)
    wb = load_workbook(BytesIO(contenido))
    ws = wb["Consolidado"]
    headers = [c.value for c in ws[1]]
    fila = {headers[i]: c.value for i, c in enumerate(ws[2])}
    assert fila["Transmisiones"] == "Sí"


def test_consolidado_udz_no_necesita_transmision(tmp_path):
    udz_activo = _escribir_udz(tmp_path, require_transmission="false")
    resultados = [_resultado_base(udz_activo=udz_activo)]
    contenido = reports.generar_excel_consolidado(resultados)
    wb = load_workbook(BytesIO(contenido))
    ws = wb["Consolidado"]
    headers = [c.value for c in ws[1]]
    fila = {headers[i]: c.value for i, c in enumerate(ws[2])}
    assert fila["Transmisiones"] == "No"


def test_consolidado_udz_con_item_envuelto(tmp_path):
    """Algunos UDZ envuelven sus campos en un objeto "item" — debe leerse
    igual desde ahí."""
    udz_activo = _escribir_udz(tmp_path, item={"require_transmission": "true"})
    resultados = [_resultado_base(udz_activo=udz_activo)]
    contenido = reports.generar_excel_consolidado(resultados)
    wb = load_workbook(BytesIO(contenido))
    ws = wb["Consolidado"]
    headers = [c.value for c in ws[1]]
    fila = {headers[i]: c.value for i, c in enumerate(ws[2])}
    assert fila["Transmisiones"] == "Sí"


def test_consolidado_archivo_faltante_muestra_guion():
    resultados = [_resultado_base()]  # sin ta_activo/aid_activo/udz_activo
    contenido = reports.generar_excel_consolidado(resultados)
    wb = load_workbook(BytesIO(contenido))
    ws = wb["Consolidado"]
    headers = [c.value for c in ws[1]]
    fila = {headers[i]: c.value for i, c in enumerate(ws[2])}
    assert fila["TA"] == "-"
    assert fila["AID Configuracion"] == "-"
    assert fila["Transmisiones"] == "-"


def test_consolidado_no_incluye_columnas_de_qa():
    """El estado de QA se muestra en la tabla de Streamlit (ui/backlog.py),
    no en este Excel — que solo trae el registro de PDN."""
    resultados = [_resultado_base()]
    contenido = reports.generar_excel_consolidado(resultados)
    wb = load_workbook(BytesIO(contenido))
    ws = wb["Consolidado"]
    headers = [c.value for c in ws[1]]
    assert "Desplegado en QA por" not in headers
    assert "Fecha despliegue QA" not in headers
    assert "Desplegado en PDN por" in headers
    assert "Fecha despliegue PDN" in headers


def test_cargas_directas_agrega_segunda_hoja():
    resultados = [_resultado_base()]
    cargas_directas = [{
        "en": "2026-01-05T10:00:00", "por": "ana", "tipo": "udz",
        "ambiente": "pdn", "tabla": "tabla-udz-pdn",
        "archivo_original": "udz_extra.json", "referencia": "Flujo piloto",
        "ok": True, "transmision": "Sí",
    }]
    contenido = reports.generar_excel_consolidado(resultados, cargas_directas=cargas_directas)
    wb = load_workbook(BytesIO(contenido))
    assert "Cargas Directas" in wb.sheetnames
    ws2 = wb["Cargas Directas"]
    headers = [c.value for c in ws2[1]]
    fila = {headers[i]: c.value for i, c in enumerate(ws2[2])}
    assert fila["Archivo"] == "udz_extra.json"
    assert fila["Transmisiones"] == "Sí"
    assert fila["Flujo / Referencia"] == "Flujo piloto"


def test_sin_cargas_directas_no_agrega_segunda_hoja():
    resultados = [_resultado_base()]
    contenido = reports.generar_excel_consolidado(resultados)
    wb = load_workbook(BytesIO(contenido))
    assert wb.sheetnames == ["Consolidado"]
