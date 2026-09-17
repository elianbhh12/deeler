import csv
import json
from pathlib import Path

from python_pipeline import group_report


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_detalle(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["Nombre de los JSONs", "Nombre TA config", "Nombre del subtipo",
                          "Cantidad de archivos con ese subtipo", "Observaciones", "Ruta JSON R3"])
        for row in rows:
            writer.writerow(row)


def test_agrupa_una_fila_por_json_y_totaliza(tmp_path):
    r3_dir = tmp_path / "R3"
    _write_json(r3_dir / "AAA.json", {"workflow_variables": {"tipoDocumento": "carta", "proceso": "p1"}, "s3_path": "s3://x/AAA"})
    _write_json(r3_dir / "BBB.json", {"workflow_variables": {"tipoDocumento": "carta", "proceso": "p2"}, "s3_path": "s3://x/BBB"})
    _write_json(r3_dir / "CCC.json", {"workflow_variables": {"tipoDocumento": "otro", "proceso": "p3"}, "s3_path": "s3://x/CCC"})

    detalle_csv = tmp_path / "detalle.csv"
    _write_detalle(detalle_csv, [
        ["AAA.json", "ta1", "carta", "2", "", "s3://x/AAA"],
        ["BBB.json", "ta1", "carta", "2", "", "s3://x/BBB"],
        ["CCC.json", "", "otro", "1", "Validar Manualmente", "s3://x/CCC"],
    ])

    out_csv = tmp_path / "out.csv"
    total_r3, suma_grupos, total_subtipos = group_report.generate(r3_dir, detalle_csv, out_csv)

    assert total_r3 == 3
    assert suma_grupos == 3
    assert total_subtipos == 2

    rows = list(csv.reader(out_csv.open(encoding="utf-8"), delimiter=";"))
    header = rows[0]
    idx_subtipo = header.index("Nombre del subtipo")
    idx_cantidad = header.index("Cantidad de archivos con ese subtipo")
    data_rows = {r[0]: r for r in rows if r and r[0] not in ("Nombre de los JSONs", "TOTAL_R3", "")}
    # Solo la primera fila del grupo "carta" trae subtipo/cantidad.
    assert data_rows["AAA.json"][idx_subtipo] == "carta"
    assert data_rows["AAA.json"][idx_cantidad] == "2"
    assert data_rows["BBB.json"][idx_subtipo] == ""
    assert data_rows["BBB.json"][idx_cantidad] == ""

    total_row = next(r for r in rows if r and r[0] == "TOTAL_R3")
    assert total_row[idx_cantidad] == "3"


def test_grupo_queda_contiguo_aunque_alfabeticamente_no_lo_este(tmp_path):
    # AAA_carta y ZZZ_carta son del mismo subtipo, pero MMM_otro cae
    # alfabeticamente entre los dos. Ninguno esta en ORDEN_REPORTE_SUBTIPOS,
    # asi que sin el fix de agrupar por grupo (no por archivo suelto) el
    # orden final seria AAA_carta, MMM_otro, ZZZ_carta - el subtipo de
    # ZZZ_carta quedaria oculto pegado a la fila de MMM_otro (subtipos
    # "trocados" en el Excel).
    r3_dir = tmp_path / "R3"
    _write_json(r3_dir / "AAA_carta.json", {"workflow_variables": {"tipoDocumento": "carta"}, "s3_path": "s3://x/AAA"})
    _write_json(r3_dir / "MMM_otro.json", {"workflow_variables": {"tipoDocumento": "otro"}, "s3_path": "s3://x/MMM"})
    _write_json(r3_dir / "ZZZ_carta.json", {"workflow_variables": {"tipoDocumento": "carta"}, "s3_path": "s3://x/ZZZ"})

    detalle_csv = tmp_path / "detalle.csv"
    _write_detalle(detalle_csv, [
        ["AAA_carta.json", "", "carta", "2", "", "s3://x/AAA"],
        ["MMM_otro.json", "", "otro", "1", "", "s3://x/MMM"],
        ["ZZZ_carta.json", "", "carta", "2", "", "s3://x/ZZZ"],
    ])

    out_csv = tmp_path / "out.csv"
    group_report.generate(r3_dir, detalle_csv, out_csv)

    all_rows = list(csv.reader(out_csv.open(encoding="utf-8"), delimiter=";"))
    idx_subtipo = all_rows[0].index("Nombre del subtipo")
    rows = [r for r in all_rows if r and r[0] not in ("Nombre de los JSONs", "TOTAL_R3")]
    nombres_en_orden = [r[0] for r in rows]
    # Las dos filas de "carta" deben quedar una al lado de la otra.
    idx_aaa = nombres_en_orden.index("AAA_carta.json")
    idx_zzz = nombres_en_orden.index("ZZZ_carta.json")
    assert abs(idx_aaa - idx_zzz) == 1, f"carta no quedo contiguo: {nombres_en_orden}"

    by_name = {r[0]: r for r in rows}
    # La fila que muestra el subtipo debe realmente ser "carta", no "otro".
    fila_con_subtipo = by_name["AAA_carta.json"] if by_name["AAA_carta.json"][idx_subtipo] else by_name["ZZZ_carta.json"]
    assert fila_con_subtipo[idx_subtipo] == "carta"


def test_columna_transmisiones_es_opcional(tmp_path):
    r3_dir = tmp_path / "R3"
    _write_json(r3_dir / "AAA.json", {"workflow_variables": {"tipoDocumento": "carta"}, "s3_path": "s3://x/AAA"})
    _write_json(r3_dir / "BBB.json", {"workflow_variables": {"tipoDocumento": "otro"}, "s3_path": "s3://x/BBB"})

    detalle_csv = tmp_path / "detalle.csv"
    _write_detalle(detalle_csv, [
        ["AAA.json", "ta1", "carta", "1", "", "s3://x/AAA"],
        ["BBB.json", "ta1", "otro", "1", "", "s3://x/BBB"],
    ])

    out_csv = tmp_path / "out.csv"
    group_report.generate(r3_dir, detalle_csv, out_csv, resultados_basenames={"AAA"})

    rows = list(csv.reader(out_csv.open(encoding="utf-8"), delimiter=";"))
    idx_transm = rows[0].index("Transmisiones")
    assert idx_transm != -1
    data_rows = {r[0]: r for r in rows if r and r[0] not in ("Nombre de los JSONs", "TOTAL_R3", "")}
    assert data_rows["AAA.json"][idx_transm] == "Si"
    assert data_rows["BBB.json"][idx_transm] == "No"


def test_columna_tipo_distingue_topics_de_ms(tmp_path):
    r3_dir = tmp_path / "R3"
    _write_json(r3_dir / "topics" / "AAA.json", {"workflow_variables": {"tipoDocumento": "carta"}, "s3_path": "s3://x/AAA"})
    _write_json(r3_dir / "ms" / "BBB.json", {"workflow_variables": {"tipoDocumento": "otro"}, "s3_path": "s3://x/BBB"})

    detalle_csv = tmp_path / "detalle.csv"
    _write_detalle(detalle_csv, [
        ["AAA.json", "", "carta", "1", "", "s3://x/AAA"],
        ["BBB.json", "", "otro", "1", "", "s3://x/BBB"],
    ])

    out_csv = tmp_path / "out.csv"
    group_report.generate(r3_dir, detalle_csv, out_csv)

    rows = list(csv.reader(out_csv.open(encoding="utf-8"), delimiter=";"))
    idx_tipo = rows[0].index("Tipo")
    data_rows = {r[0]: r for r in rows if r and r[0] not in ("Nombre de los JSONs", "TOTAL_R3", "")}
    assert data_rows["AAA.json"][idx_tipo] == "R3 - Topics"
    assert data_rows["BBB.json"][idx_tipo] == "R3 - MS"


def test_snapshot_rows_para_historial(tmp_path):
    r3_dir = tmp_path / "R3"
    _write_json(r3_dir / "AAA.json", {"workflow_variables": {"tipoDocumento": "carta"}, "s3_path": "s3://x/AAA"})

    detalle_csv = tmp_path / "detalle.csv"
    _write_detalle(detalle_csv, [["AAA.json", "ta1", "carta", "1", "", "s3://x/AAA"]])

    rows = group_report.snapshot_rows(r3_dir, detalle_csv, resultados_basenames={"AAA"})

    assert len(rows) == 1
    row = rows[0]
    assert row["file"] == "AAA.json"
    assert row["subtipo"] == "carta"
    assert row["ta_config"] == "ta1"
    assert row["transmisiones"] == "Si"
    assert row["proceso"] == "SIN_PROCESO"
    assert row["s3_path"] == "s3://x/AAA"
