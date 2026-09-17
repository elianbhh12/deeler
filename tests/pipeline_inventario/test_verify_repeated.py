import json
from pathlib import Path

from python_pipeline import verify_repeated


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_detecta_subtipo_repetido(tmp_path):
    r3_dir = tmp_path / "R3"
    _write_json(r3_dir / "AAA.json", {"workflow_variables": {"tipoDocumento": "Carta Prueba", "proceso": "p1"}})
    _write_json(r3_dir / "BBB.json", {"workflow_variables": {"tipoDocumento": "carta prueba", "proceso": "p2"}})
    _write_json(r3_dir / "CCC.json", {"workflow_variables": {"tipoDocumento": "unico", "proceso": "p3"}})

    out_txt = tmp_path / "out.txt"
    summary = verify_repeated.verify_repeated(str(r3_dir), out_txt)

    assert summary["repeated_subtypes"] == 1
    content = out_txt.read_text(encoding="utf-8")
    assert "Cantidad de archivos: 2" in content
    assert "AAA.json" in content and "BBB.json" in content
    assert "CCC.json" not in content


def test_sin_repetidos(tmp_path):
    r3_dir = tmp_path / "R3"
    _write_json(r3_dir / "AAA.json", {"workflow_variables": {"tipoDocumento": "uno"}})
    _write_json(r3_dir / "BBB.json", {"workflow_variables": {"tipoDocumento": "dos"}})

    out_txt = tmp_path / "out.txt"
    summary = verify_repeated.verify_repeated(str(r3_dir), out_txt)

    assert summary["repeated_subtypes"] == 0
    assert "No se encontraron subtipos repetidos" in out_txt.read_text(encoding="utf-8")


def test_lista_objetivo_reporta_faltantes(tmp_path):
    r3_dir = tmp_path / "R3"
    _write_json(r3_dir / "AAA.json", {"workflow_variables": {"tipoDocumento": "uno"}})

    lista = tmp_path / "lista.txt"
    lista.write_text("AAA.json\nNO_EXISTE.json\n", encoding="utf-8")

    out_txt = tmp_path / "out.txt"
    summary = verify_repeated.verify_repeated(str(r3_dir), out_txt, lista)

    assert summary["total_requested"] == 2
    assert summary["missing"] == 1
    assert "NO_EXISTE.json" in out_txt.read_text(encoding="utf-8")


def test_errores_de_parseo_se_reportan(tmp_path):
    r3_dir = tmp_path / "R3"
    r3_dir.mkdir(parents=True)
    (r3_dir / "roto.json").write_text("{invalido", encoding="utf-8")

    out_txt = tmp_path / "out.txt"
    summary = verify_repeated.verify_repeated(str(r3_dir), out_txt)

    assert summary["parse_errors"] == 1
