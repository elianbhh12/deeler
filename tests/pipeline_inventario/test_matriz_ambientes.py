import json

from python_pipeline import matriz_ambientes


def test_primer_ambiente_todo_presente(tmp_path, monkeypatch):
    monkeypatch.setattr(matriz_ambientes, "ESTADO_FILE", tmp_path / "matriz.json")

    filas = [{"file": "AAA.json", "subtipo": "carta"}]
    data = matriz_ambientes.actualizar("qa", filas, fecha="2026-09-15")

    assert data["AAA.json"]["qa"] == {"presente": True, "subtipo": "carta", "ultima_vez": "2026-09-15"}
    assert "pdn" not in data["AAA.json"]  # nunca visto en pdn -> ni siquiera aparece la clave


def test_segundo_ambiente_no_borra_el_primero(tmp_path, monkeypatch):
    monkeypatch.setattr(matriz_ambientes, "ESTADO_FILE", tmp_path / "matriz.json")

    matriz_ambientes.actualizar("qa", [{"file": "AAA.json", "subtipo": "carta"}], fecha="2026-09-15")
    data = matriz_ambientes.actualizar("pdn", [{"file": "AAA.json", "subtipo": "carta"}], fecha="2026-09-16")

    assert data["AAA.json"]["qa"]["presente"] is True
    assert data["AAA.json"]["pdn"]["presente"] is True


def test_flujo_desaparecido_queda_marcado_no_borrado_en_modo_completo(tmp_path, monkeypatch):
    """Solo en modo "completo" un flujo ausente de filas_actuales se marca
    presente=False -- en ese modo filas_actuales sí representa TODO lo que
    hay hoy en la tabla, así que lo que falta realmente se borró."""
    monkeypatch.setattr(matriz_ambientes, "ESTADO_FILE", tmp_path / "matriz.json")

    matriz_ambientes.actualizar("qa", [{"file": "AAA.json", "subtipo": "carta"}], modo="completo", fecha="2026-09-15")
    data = matriz_ambientes.actualizar("qa", [], modo="completo", fecha="2026-09-16")

    assert data["AAA.json"]["qa"]["presente"] is False
    assert data["AAA.json"]["qa"]["subtipo"] == "carta"  # se conserva el ultimo subtipo conocido


def test_modo_incremental_no_marca_ausentes(tmp_path, monkeypatch):
    """Regresión: en modo "incremental" (default), filas_actuales solo trae
    lo NUEVO desde la última descarga -- casi ningún flujo conocido vuelve a
    aparecer ahí aunque siga existiendo, así que NO debe marcarse como
    ausente (antes de este fix, cualquier corrida incremental marcaba casi
    todo lo conocido como presente=False)."""
    monkeypatch.setattr(matriz_ambientes, "ESTADO_FILE", tmp_path / "matriz.json")

    matriz_ambientes.actualizar("qa", [{"file": "AAA.json", "subtipo": "carta"}], modo="completo", fecha="2026-09-15")
    data = matriz_ambientes.actualizar("qa", [], modo="incremental", fecha="2026-09-16")

    assert data["AAA.json"]["qa"]["presente"] is True


def test_persiste_en_disco_entre_llamadas(tmp_path, monkeypatch):
    estado_file = tmp_path / "matriz.json"
    monkeypatch.setattr(matriz_ambientes, "ESTADO_FILE", estado_file)

    matriz_ambientes.actualizar("qa", [{"file": "AAA.json", "subtipo": "carta"}], fecha="2026-09-15")

    on_disk = json.loads(estado_file.read_text(encoding="utf-8"))
    assert on_disk["AAA.json"]["qa"]["presente"] is True


def test_cargar_estado(tmp_path, monkeypatch):
    monkeypatch.setattr(matriz_ambientes, "ESTADO_FILE", tmp_path / "matriz.json")
    matriz_ambientes.actualizar("qa", [{"file": "AAA.json", "subtipo": "carta"}], fecha="2026-09-15")

    assert matriz_ambientes.cargar_estado() == {
        "AAA.json": {"qa": {"presente": True, "subtipo": "carta", "ultima_vez": "2026-09-15"}}
    }
