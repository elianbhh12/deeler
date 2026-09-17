import json

from python_pipeline import historial


def test_primera_corrida_todo_es_nuevo(tmp_path, monkeypatch):
    monkeypatch.setattr(historial, "HISTORIAL_DIR", tmp_path)

    filas = [
        {"file": "AAA.json", "subtipo": "carta", "ta_config": "ta1", "transmisiones": "Si"},
        {"file": "BBB.json", "subtipo": "otro", "ta_config": "", "transmisiones": "No"},
    ]
    resumen = historial.actualizar("qa", filas, fecha="2026-09-15")

    assert set(resumen["nuevos"]) == {"AAA.json", "BBB.json"}
    assert resumen["eliminados"] == []
    assert resumen["cambios"] == []

    estado = json.loads((tmp_path / "qa" / "estado_actual.json").read_text(encoding="utf-8"))
    assert estado["AAA.json"]["subtipo"] == "carta"
    assert estado["AAA.json"]["primera_vez"] == "2026-09-15"


def test_modo_completo_detecta_nuevo_eliminado_y_cambio(tmp_path, monkeypatch):
    monkeypatch.setattr(historial, "HISTORIAL_DIR", tmp_path)

    primera = [
        {"file": "AAA.json", "subtipo": "carta", "ta_config": "ta1", "transmisiones": "Si"},
        {"file": "BBB.json", "subtipo": "otro", "ta_config": "", "transmisiones": "No"},
    ]
    historial.actualizar("qa", primera, modo="completo", fecha="2026-09-15")

    segunda = [
        {"file": "AAA.json", "subtipo": "carta_editada", "ta_config": "ta1", "transmisiones": "Si"},  # cambio subtipo
        {"file": "CCC.json", "subtipo": "nuevo_flujo", "ta_config": "", "transmisiones": "No"},        # nuevo
        # BBB.json desaparece -> en modo completo, se sabe que ya no esta -> eliminado
    ]
    resumen = historial.actualizar("qa", segunda, modo="completo", fecha="2026-09-16")

    assert resumen["nuevos"] == ["CCC.json"]
    assert resumen["eliminados"] == ["BBB.json"]
    assert resumen["cambios"] == ["AAA.json"]

    estado = json.loads((tmp_path / "qa" / "estado_actual.json").read_text(encoding="utf-8"))
    assert estado["BBB.json"]["presente"] is False  # se conserva el registro, solo se marca ausente
    assert estado["AAA.json"]["subtipo"] == "carta_editada"
    assert estado["AAA.json"]["primera_vez"] == "2026-09-15"  # se conserva
    assert estado["AAA.json"]["ultima_vez"] == "2026-09-16"


def test_modo_incremental_no_marca_eliminados(tmp_path, monkeypatch):
    monkeypatch.setattr(historial, "HISTORIAL_DIR", tmp_path)

    primera = [
        {"file": "AAA.json", "subtipo": "carta", "ta_config": "ta1", "transmisiones": "Si"},
        {"file": "BBB.json", "subtipo": "otro", "ta_config": "", "transmisiones": "No"},
    ]
    historial.actualizar("qa", primera, modo="completo", fecha="2026-09-15")

    # Descarga incremental de hoy: solo trajo CCC (nuevo). BBB no aparece
    # porque no se volvio a descargar (sigue existiendo en Dynamo), NO
    # porque haya sido eliminado -- con datos parciales no se puede saber.
    segunda = [{"file": "CCC.json", "subtipo": "nuevo_flujo", "ta_config": "", "transmisiones": "No"}]
    resumen = historial.actualizar("qa", segunda, modo="incremental", fecha="2026-09-16")

    assert resumen["nuevos"] == ["CCC.json"]
    assert resumen["eliminados"] == []  # NADA se marca eliminado en modo incremental

    presentes = {f["file"] for f in historial.flujos_presentes("qa")}
    assert presentes == {"AAA.json", "BBB.json", "CCC.json"}  # BBB sigue "presente"


def test_sin_cambios_no_genera_eventos(tmp_path, monkeypatch):
    monkeypatch.setattr(historial, "HISTORIAL_DIR", tmp_path)

    filas = [{"file": "AAA.json", "subtipo": "carta", "ta_config": "ta1", "transmisiones": "Si"}]
    historial.actualizar("qa", filas, fecha="2026-09-15")
    resumen = historial.actualizar("qa", filas, fecha="2026-09-16")

    assert resumen == {"nuevos": [], "eliminados": [], "cambios": []}


def test_eventos_se_acumulan_entre_corridas(tmp_path, monkeypatch):
    monkeypatch.setattr(historial, "HISTORIAL_DIR", tmp_path)

    historial.actualizar("qa", [{"file": "AAA.json", "subtipo": "carta", "ta_config": "", "transmisiones": ""}], modo="completo", fecha="2026-09-15")
    historial.actualizar("qa", [{"file": "BBB.json", "subtipo": "otro", "ta_config": "", "transmisiones": ""}], modo="completo", fecha="2026-09-16")

    eventos = historial.eventos_completos("qa")
    tipos_por_flujo = [(ev["flujo"], ev["tipo"]) for ev in eventos]
    # AAA nuevo el 15, luego eliminado el 16 (ya no aparece en una corrida
    # completa), BBB nuevo el 16
    assert ("AAA.json", "NUEVO") in tipos_por_flujo
    assert ("AAA.json", "ELIMINADO") in tipos_por_flujo
    assert ("BBB.json", "NUEVO") in tipos_por_flujo


def test_ambientes_no_se_mezclan(tmp_path, monkeypatch):
    monkeypatch.setattr(historial, "HISTORIAL_DIR", tmp_path)

    historial.actualizar("qa", [{"file": "AAA.json", "subtipo": "x", "ta_config": "", "transmisiones": ""}], fecha="2026-09-15")
    resumen_pdn = historial.actualizar("pdn", [{"file": "AAA.json", "subtipo": "x", "ta_config": "", "transmisiones": ""}], fecha="2026-09-15")

    # Mismo flujo, pero pdn no tiene historial previo -> sigue siendo "nuevo" ahi
    assert resumen_pdn["nuevos"] == ["AAA.json"]


def test_flujos_presentes_incluye_todos_los_campos(tmp_path, monkeypatch):
    monkeypatch.setattr(historial, "HISTORIAL_DIR", tmp_path)

    filas = [{
        "file": "AAA.json", "subtipo": "carta", "ta_config": "ta1",
        "proceso": "proceso1", "s3_path": "s3://x/AAA", "observacion": "obs",
        "transmisiones": "Si", "tipo": "R3 - Topics",
    }]
    historial.actualizar("qa", filas, fecha="2026-09-15")

    presentes = historial.flujos_presentes("qa")
    assert len(presentes) == 1
    assert presentes[0]["file"] == "AAA.json"
    assert presentes[0]["proceso"] == "proceso1"
    assert presentes[0]["tipo"] == "R3 - Topics"


def test_modo_invalido_lanza_error(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(historial, "HISTORIAL_DIR", tmp_path)
    with pytest.raises(ValueError):
        historial.actualizar("qa", [], modo="rapido")
