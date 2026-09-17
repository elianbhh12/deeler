import csv
import json
from pathlib import Path

from python_pipeline import compare


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _read_csv(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh, delimiter=";"))


def test_compare_marca_comparte_ta_y_no_clasificados(tmp_path):
    r3_dir = tmp_path / "R3"
    ta_dir = tmp_path / "TA"

    _write_json(r3_dir / "AAA_TEST.json", {
        "s3_path": "s3://bucket/udz/AAA_TEST",
        "workflow_variables": {"tipoDocumento": "carta_prueba", "proceso": "proceso_uno"},
        "STEP_VARIABLES": {"use_case": "ta_carta_prueba"},
    })
    _write_json(r3_dir / "BBB_TEST.json", {
        "s3_path": "s3://bucket/udz/BBB_TEST",
        "workflow_variables": {"tipoDocumento": "carta_prueba", "proceso": "proceso_dos"},
        "STEP_VARIABLES": {"use_case": "ta_carta_prueba"},
    })
    _write_json(r3_dir / "CCC_SINTA.json", {
        "s3_path": "s3://bucket/udz/CCC_SINTA",
        "workflow_variables": {"tipoDocumento": "otro_subtipo", "proceso": "proceso_tres"},
        "STEP_VARIABLES": {"use_case": "no_existe_en_ta"},
    })
    _write_json(ta_dir / "ta1.json", {"cu_name": "ta_carta_prueba"})

    out_dir = tmp_path / "out"
    summary = compare.compare(r3_dir, ta_dir, out_dir)

    assert summary["total_r3"] == 3
    assert summary["matched"] == 2
    assert summary["unmatched"] == 1
    assert summary["missing_use_case"] == 0

    classified_rows = _read_csv(out_dir / "clasificados" / "ta_cu_name.txt")
    body = classified_rows[1:]
    comparte_by_name = {row[0]: row[3] for row in body}
    assert comparte_by_name["AAA_TEST.json"] == "Si: BBB_TEST.json"
    assert comparte_by_name["BBB_TEST.json"] == "Si: AAA_TEST.json"

    unclassified_rows = _read_csv(out_dir / "no_clasificados" / "r3_sin_ta.txt")
    assert unclassified_rows[1][0] == "CCC_SINTA.json"
    assert unclassified_rows[1][3] == "Validar Manualmente"


def test_compare_sin_use_case_usa_observacion_manual(tmp_path):
    r3_dir = tmp_path / "R3"
    ta_dir = tmp_path / "TA"
    _write_json(r3_dir / "aid_test_000079.json", {
        "s3_path": "s3://bucket/udz/aid_test_000079",
        "workflow_variables": {"tipoDocumento": "test"},
    })
    _write_json(ta_dir / "ta1.json", {"cu_name": "algo"})

    out_dir = tmp_path / "out"
    summary = compare.compare(r3_dir, ta_dir, out_dir)

    assert summary["missing_use_case"] == 1
    rows = _read_csv(out_dir / "no_clasificados" / "r3_sin_ta.txt")
    assert rows[1][3] == "Caso de prueba, usa TA con la config en el mismo archivo"


def test_compare_falla_si_no_existen_directorios(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        compare.compare(tmp_path / "no_existe_r3", tmp_path / "no_existe_ta", tmp_path / "out")
