import csv
import json
from pathlib import Path

import pytest

from python_pipeline import new_vs_baseline


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_detecta_nuevos_respecto_al_baseline(tmp_path):
    r3_dir = tmp_path / "R3"
    _write_json(r3_dir / "CONOCIDO.json", {"workflow_variables": {"tipoDocumento": "carta"}, "s3_path": "s3://x/CONOCIDO"})
    _write_json(r3_dir / "NUEVO.json", {"workflow_variables": {"tipoDocumento": "otro"}, "s3_path": "s3://x/NUEVO"})

    orden_file = tmp_path / "Orden_RE_Base.txt"
    orden_file.write_text("CONOCIDO.json\n", encoding="utf-8")

    out_csv = tmp_path / "nuevos.csv"
    total = new_vs_baseline.generate(r3_dir, orden_file, out_csv)

    assert total == 1
    rows = list(csv.reader(out_csv.open(encoding="utf-8"), delimiter=";"))
    assert rows[1][0] == "NUEVO.json"


def test_sin_baseline_lanza_error_claro(tmp_path):
    r3_dir = tmp_path / "R3"
    r3_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        new_vs_baseline.generate(r3_dir, tmp_path / "no_existe.txt", tmp_path / "out.csv")


def test_usa_detalle_csv_si_esta_disponible(tmp_path):
    r3_dir = tmp_path / "R3"
    _write_json(r3_dir / "NUEVO.json", {"workflow_variables": {"tipoDocumento": "otro"}, "s3_path": "s3://x/NUEVO"})

    orden_file = tmp_path / "Orden_RE_Base.txt"
    orden_file.write_text("", encoding="utf-8")

    detalle_csv = tmp_path / "detalle.csv"
    with detalle_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["Nombre de los JSONs", "Nombre TA config", "Nombre del subtipo",
                          "Cantidad de archivos con ese subtipo", "Observaciones", "Ruta JSON R3"])
        writer.writerow(["NUEVO.json", "ta_config_x", "otro", "5", "obs", "s3://x/NUEVO"])

    out_csv = tmp_path / "nuevos.csv"
    new_vs_baseline.generate(r3_dir, orden_file, out_csv, detalle_csv)

    rows = list(csv.reader(out_csv.open(encoding="utf-8"), delimiter=";"))
    assert rows[1][1] == "ta_config_x"
    assert rows[1][3] == "5"
