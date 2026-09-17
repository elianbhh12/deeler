import json
from pathlib import Path

from python_pipeline import sharepoint_source

FALLBACK = ["A.json", "B.json"]


def _write_config(path: Path, **overrides) -> None:
    data = {
        "activo": True,
        "ruta_archivo": "no_existe.xlsx",
        "hoja": "Orden",
        "columna": "Nombre del Flujo",
        "fila_encabezado": 1,
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_master_excel(path: Path, sheet_name="Orden", header="Nombre del Flujo", values=None):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(["Otra columna", header])
    for v in values or []:
        ws.append(["x", v])
    wb.save(path)


def test_config_inexistente_usa_fallback(tmp_path):
    result = sharepoint_source.load_orden_reporte(tmp_path / "no_existe.json", FALLBACK)
    assert result == FALLBACK


def test_config_inactivo_usa_fallback(tmp_path):
    config_file = tmp_path / "fuente.json"
    _write_config(config_file, activo=False)
    result = sharepoint_source.load_orden_reporte(config_file, FALLBACK)
    assert result == FALLBACK


def test_archivo_excel_no_existe_usa_fallback(tmp_path):
    config_file = tmp_path / "fuente.json"
    _write_config(config_file, ruta_archivo=str(tmp_path / "no_existe.xlsx"))
    result = sharepoint_source.load_orden_reporte(config_file, FALLBACK)
    assert result == FALLBACK


def test_lee_columna_correctamente(tmp_path):
    excel_path = tmp_path / "maestro.xlsx"
    _write_master_excel(excel_path, values=["FLUJO_1", "FLUJO_2", "FLUJO_3"])

    config_file = tmp_path / "fuente.json"
    _write_config(config_file, ruta_archivo=str(excel_path))

    result = sharepoint_source.load_orden_reporte(config_file, FALLBACK)
    assert result == ["FLUJO_1", "FLUJO_2", "FLUJO_3"]


def test_hoja_incorrecta_usa_fallback(tmp_path):
    excel_path = tmp_path / "maestro.xlsx"
    _write_master_excel(excel_path, sheet_name="Orden", values=["X"])

    config_file = tmp_path / "fuente.json"
    _write_config(config_file, ruta_archivo=str(excel_path), hoja="NoExiste")

    result = sharepoint_source.load_orden_reporte(config_file, FALLBACK)
    assert result == FALLBACK


def test_columna_incorrecta_usa_fallback(tmp_path):
    excel_path = tmp_path / "maestro.xlsx"
    _write_master_excel(excel_path, header="Nombre del Flujo", values=["X"])

    config_file = tmp_path / "fuente.json"
    _write_config(config_file, ruta_archivo=str(excel_path), columna="NoExiste")

    result = sharepoint_source.load_orden_reporte(config_file, FALLBACK)
    assert result == FALLBACK


def test_columna_vacia_usa_fallback(tmp_path):
    excel_path = tmp_path / "maestro.xlsx"
    _write_master_excel(excel_path, values=[])

    config_file = tmp_path / "fuente.json"
    _write_config(config_file, ruta_archivo=str(excel_path))

    result = sharepoint_source.load_orden_reporte(config_file, FALLBACK)
    assert result == FALLBACK
