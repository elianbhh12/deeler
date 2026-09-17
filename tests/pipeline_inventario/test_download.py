import json
from decimal import Decimal
from pathlib import Path

from python_pipeline.download import _ScanState, _auto_segment_count, _classify_item


def test_auto_segment_count_tabla_chica():
    assert _auto_segment_count(3) == 1
    assert _auto_segment_count(500) == 1


def test_auto_segment_count_crece_con_el_tamano():
    assert _auto_segment_count(5_000) == 2
    assert _auto_segment_count(50_000) == 4
    assert _auto_segment_count(1_000_000) == 8


def test_auto_segment_count_sin_dato_es_conservador():
    assert _auto_segment_count("N/D") == 1


def test_classify_config_control_r2():
    folder, name = _classify_item("config-control", {"s3_path": "s3://bucket/r2-raw/algo/final"}, 0)
    assert folder == "R2"
    assert name == "final"


def test_classify_config_control_r3_ms():
    item = {"s3_path": "s3://bucket/udz/MI_FLUJO", "workflow_definition": []}
    folder, _ = _classify_item("config-control", item, 0)
    assert folder == "R3/ms"


def test_classify_config_control_r3_topics():
    item = {
        "s3_path": "s3://bucket/udz/MI_FLUJO",
        "workflow_definition": [{"THREADS": [{"STEPS": [{"TYPE": "topic"}]}]}],
    }
    folder, _ = _classify_item("config-control", item, 0)
    assert folder == "R3/topics"


def test_classify_config_control_sin_s3_path_es_r3_nuevos():
    folder, name = _classify_item("config-control", {}, 7)
    assert folder == "R3_Nuevos"
    assert name == "item_7"


def test_classify_text_analyzer_use_case():
    item = {"cu_name": "ta_x", "pasos": [{"STEP_VARIABLES": {"use_case": "algo"}}]}
    folder, name = _classify_item("text-analyzer", item, 0)
    assert folder == "use_case"
    assert name == "ta_x"


def test_classify_text_analyzer_use_case_ta():
    item = {"cu_name": "ta_y"}
    folder, name = _classify_item("text-analyzer", item, 0)
    assert folder == "use_case_TA"
    assert name == "ta_y"


def test_classify_events_manager_crudos():
    item = {"s3_path": "s3://b/crudos/ns_x/FLUJO_A"}
    folder, name = _classify_item("events-manager", item, 0)
    assert folder == "crudos"
    assert name == "FLUJO_A"


def test_classify_events_manager_resultados():
    item = {"s3_path": "s3://b/resultados/ns_x/FLUJO_A"}
    folder, name = _classify_item("events-manager", item, 0)
    assert folder == "resultados"


def test_scan_state_escribe_archivo_y_cuenta(tmp_path):
    state = _ScanState("config-control", tmp_path, None, "s3_path", set(), dry_run=False)
    state.process_item({"s3_path": "s3://bucket/udz/AAA"})

    assert state.total_saved == 1
    saved_file = tmp_path / "R3" / "ms" / "AAA.json"
    assert saved_file.exists()
    assert json.loads(saved_file.read_text(encoding="utf-8"))["s3_path"] == "s3://bucket/udz/AAA"


def test_scan_state_dry_run_no_escribe_nada(tmp_path):
    state = _ScanState("config-control", tmp_path, None, "s3_path", set(), dry_run=True)
    state.process_item({"s3_path": "s3://bucket/udz/AAA"})

    assert state.total_saved == 1
    assert not (tmp_path / "R3").exists()


def test_scan_state_incremental_omite_items_ya_conocidos(tmp_path):
    # Modo incremental (default, completo=False): rapido, no vuelve a
    # escribir lo que ya se conocia. La "verdad completa" de cada ambiente
    # ya no depende de esto -- vive en el maestro acumulado (maestro.py).
    existing = {"s3://bucket/udz/AAA"}
    state = _ScanState("config-control", tmp_path, tmp_path / "ref", "s3_path", existing, dry_run=False)
    state.process_item({"s3_path": "s3://bucket/udz/AAA"})  # ya conocido
    state.process_item({"s3_path": "s3://bucket/udz/BBB"})  # nuevo

    assert state.total_saved == 1  # solo BBB
    assert state.total_existentes_referencia == 1  # AAA, contado pero no escrito
    assert not (tmp_path / "R3" / "ms" / "AAA.json").exists()
    assert (tmp_path / "R3" / "ms" / "BBB.json").exists()
    assert len(state.report_lines) == 1
    assert "BBB" in state.report_lines[0]


def test_scan_state_completo_guarda_todo_incluso_lo_ya_conocido(tmp_path):
    # Modo completo (completo=True, explicito): siempre guarda todo, sin
    # importar la referencia. Es el modo a usar cuando se quiere una foto
    # 100% confiable de la tabla en el momento (ej. para reconciliar el
    # maestro y detectar eliminados de verdad).
    existing = {"s3://bucket/udz/AAA"}
    state = _ScanState("config-control", tmp_path, tmp_path / "ref", "s3_path", existing, dry_run=False, completo=True)
    state.process_item({"s3_path": "s3://bucket/udz/AAA"})
    state.process_item({"s3_path": "s3://bucket/udz/BBB"})

    assert state.total_saved == 2
    assert state.total_existentes_referencia == 1
    assert (tmp_path / "R3" / "ms" / "AAA.json").exists()
    assert (tmp_path / "R3" / "ms" / "BBB.json").exists()


def test_scan_state_serializa_decimales_de_dynamo(tmp_path):
    # TypeDeserializer devuelve Decimal para los numeros ("N") de Dynamo;
    # esto no debe reventar al escribir el JSON a disco.
    state = _ScanState("config-control", tmp_path, None, "s3_path", set(), dry_run=False)
    state.process_item({
        "s3_path": "s3://bucket/udz/CON_NUMEROS",
        "version": Decimal("3"),
        "porcentaje": Decimal("12.5"),
    })

    saved_file = tmp_path / "R3" / "ms" / "CON_NUMEROS.json"
    data = json.loads(saved_file.read_text(encoding="utf-8"))
    assert data["version"] == 3
    assert isinstance(data["version"], int)
    assert data["porcentaje"] == 12.5


def test_scan_state_resuelve_colision_de_nombre(tmp_path):
    state = _ScanState("config-control", tmp_path, None, "s3_path", set(), dry_run=False)
    state.process_item({"s3_path": "s3://bucket/udz/AAA/final"})
    state.process_item({"s3_path": "s3://bucket/otra_ruta/udz/final"})

    assert state.total_saved == 2
    files = sorted(p.name for p in (tmp_path / "R3" / "ms").glob("*.json"))
    assert len(files) == 2
    assert "final.json" in files
    assert any(name != "final.json" for name in files)
