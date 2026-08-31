import json
from pathlib import Path

import pytest


#  Helpers de bajo nivel

def test_buscar_clave_encuentra_anidado(appmod):
    data = {"a": {"b": [{"c": 1}, {"target": "valor"}]}}
    assert appmod.buscar_clave(data, "target") == "valor"


def test_buscar_clave_no_encontrada_retorna_none(appmod):
    assert appmod.buscar_clave({"a": 1}, "no_existe") is None


def test_buscar_clave_todos_acumula_todas_las_ocurrencias(appmod):
    data = {"steps": [{"LAST_STEP": "False"}, {"LAST_STEP": "True"}]}
    out = []
    appmod.buscar_clave_todos(data, "LAST_STEP", out)
    assert out == ["False", "True"]


@pytest.mark.parametrize("s3, esperado", [
    ("s3://bucket-pdn-x/resultados", "PDN"),
    ("s3://bucket-prod-x/resultados", "PDN"),
    ("s3://bucket-qa-x/resultados", "QA"),
    ("s3://bucket-dev-x/resultados", "DEV"),
    ("s3://bucket-uat-x/resultados", "UAT"),
    ("s3://bucket-x/resultados", "DESCONOCIDO"),
])
def test_detectar_ambiente(appmod, s3, esperado):
    assert appmod.detectar_ambiente(s3) == esperado


def test_normalizar_s3_ignora_slash_final(appmod):
    assert appmod.normalizar_s3("s3://bucket/ruta/") == appmod.normalizar_s3("s3://bucket/ruta")


#  estado_code / estado_general (contrato lógica-vs-presentación)

def test_get_estado_code_usa_estado_code_si_existe(appmod):
    r = {"estado_code": appmod.ESTADO_ERROR, "estado_general": "cualquier texto"}
    assert appmod.get_estado_code(r) == appmod.ESTADO_ERROR


def test_get_estado_code_infiere_de_estado_general_si_falta(appmod):
    """Compatibilidad con análisis guardados antes de introducir estado_code."""
    r_listo = {"estado_general": f"{appmod.ICON_OK} LISTO"}
    r_error = {"estado_general": f"{appmod.ICON_ERROR} ERRORES CRÍTICOS"}
    assert appmod.get_estado_code(r_listo) == appmod.ESTADO_LISTO
    assert appmod.get_estado_code(r_error) == appmod.ESTADO_ERROR


#  analizar_hu sobre las HU de ejemplo (Backlog_Dealer/)

def test_analizar_hu_despliegue_correcto_queda_listo(appmod, tmp_path):
    # Se arma la HU con archivos propios (no la carpeta compartida de
    # Backlog_Dealer/) porque esa es de uso manual y cualquiera puede
    # reemplazar sus JSON para probar casos reales — no debe ser un fixture
    # fijo del que dependa la suite de tests.
    ta = {
        "cu_name": "caso_ok", "type": "prompts",
        "kafka_output_topic": appmod.KAFKA_TOPIC_REQUERIDO,
    }
    aid = {
        "workflow_name": "aid-pdn-ok", "s3_path": "s3://bucket-pdn-ok/resultados",
        "use_case": "caso_ok", "TYPE": "topic",
        "workflow_variables": {"tecnologia": "AID"},
        "workflow_definition": [{"STEP_NAME": "step1", "TYPE": "topic", "LAST_STEP": "False"}],
    }
    udz = {"item": {
        "id": "aid-pdn-ok", "s3_path": "s3://bucket-pdn-ok/resultados",
        "require_transmission": "true", "emit_event": "false",
    }}
    hu_folder = _escribir_hu_minima(tmp_path, ta, aid, udz, "DESPLIEGUE")

    r = appmod.analizar_hu(hu_folder)
    assert r["estado_code"] == appmod.ESTADO_LISTO


def test_analizar_hu_modificacion_solo_ta_queda_listo(appmod, fixtures_dir):
    r = appmod.analizar_hu(fixtures_dir / "1002-Modificacion Prompt PIA")
    assert r["estado_code"] == appmod.ESTADO_LISTO
    assert r["tipo_cambio"] == "MODIFICACIÓN"


def test_analizar_hu_despliegue_con_inconsistencias_queda_en_error(appmod, fixtures_dir):
    r = appmod.analizar_hu(fixtures_dir / "1003-Despliegue Con Errores PIA")
    assert r["estado_code"] == appmod.ESTADO_ERROR


#  Regresión: out_zone_copiar debe poder bloquear el estado

def _escribir_hu_minima(base: Path, ta: dict, aid: dict, udz: dict, tipo_cambio: str) -> Path:
    hu = base / "9001-hu-test"
    adj = hu / "adjuntos"
    adj.mkdir(parents=True, exist_ok=True)
    (hu / "metadata.json").write_text(json.dumps({
        "id": 9001, "title": "HU de prueba", "state": "Active",
        "tipo_cambio": tipo_cambio, "downloaded_at": "2026-01-01T00:00:00",
        "attachments": [],
    }), encoding="utf-8")
    (adj / "ta_test.json").write_text(json.dumps(ta), encoding="utf-8")
    (adj / "aid_test.json").write_text(json.dumps(aid), encoding="utf-8")
    (adj / "udz_test.json").write_text(json.dumps(udz), encoding="utf-8")
    return hu


def test_out_zone_sin_copiar_bucket_bloquea_el_estado(appmod, tmp_path):
    """Regresión del bug donde out_zone_copiar nunca podía marcar ERROR: la clave
    'ok' que leía el agregador de criticos no existía en ese dict (solo existían
    out_zone_ok/copiar_ok), así que .get('ok', True) siempre devolvía True."""
    ta = {
        "cu_name": "caso_test", "type": "prompts",
        "kafka_output_topic": "documentreceivingmanagement.documentuploadedv1",
    }
    aid = {
        "workflow_name": "aid-pdn-test", "s3_path": "s3://bucket-pdn-test/resultados",
        "use_case": "caso_test", "TYPE": "topic",
        "workflow_variables": {"tecnologia": "AID"},
        "workflow_definition": [{
            "STEP_NAME": "step1", "FUNCTION_NAME": "call_api", "LAST_STEP": "False",
            "STEP_VARIABLES": {"JOB_NAME": "job1", "out_zone": "s3://bucket-pdn-test/out/"},
            # out_zone presente pero SIN copiarResultadoBucket -> debe ser error
        }],
    }
    udz = {"item": {
        "id": "aid-pdn-test", "s3_path": "s3://bucket-pdn-test/resultados",
        "require_transmission": "true", "emit_event": "false",
    }}
    hu_folder = _escribir_hu_minima(tmp_path, ta, aid, udz, "DESPLIEGUE")

    r = appmod.analizar_hu(hu_folder)

    assert r["validaciones"]["out_zone_copiar"]["out_zone_ok"] is False
    assert r["estado_code"] == appmod.ESTADO_ERROR, (
        "out_zone sin copiarResultadoBucket=True debe bloquear el estado LISTO"
    )


#  Regresión: kafka_output_topic y TYPE deben validar TODAS las ocurrencias, no solo la primera

def test_kafka_topic_detecta_mismatch_en_ocurrencia_no_primera(appmod, tmp_path):
    ta = {
        "cu_name": "caso_multi", "type": "prompts",
        "data": {
            "kafka_output_topic": appmod.KAFKA_TOPIC_REQUERIDO,
            "extra_step": {"kafka_output_topic": "otro.topic.incorrecto"},
        },
    }
    aid = {
        "workflow_name": "aid-pdn-multi", "s3_path": "s3://bucket-pdn-multi/resultados",
        "use_case": "caso_multi", "TYPE": "topic",
        "workflow_variables": {"tecnologia": "AID"},
        "workflow_definition": [{"STEP_NAME": "step1", "LAST_STEP": "False"}],
    }
    udz = {"item": {
        "id": "aid-pdn-multi", "s3_path": "s3://bucket-pdn-multi/resultados",
        "require_transmission": "true", "emit_event": "false",
    }}
    hu_folder = _escribir_hu_minima(tmp_path, ta, aid, udz, "DESPLIEGUE")

    r = appmod.analizar_hu(hu_folder)

    assert len(r["validaciones"]["kafka"]["topics"]) == 2
    assert r["validaciones"]["kafka"]["ok"] is False, (
        "si CUALQUIER ocurrencia de kafka_output_topic no coincide, la validación debe fallar"
    )


def test_aid_type_detecta_mismatch_en_step_no_primero(appmod, tmp_path):
    ta = {
        "cu_name": "caso_multi2", "type": "prompts",
        "kafka_output_topic": appmod.KAFKA_TOPIC_REQUERIDO,
    }
    aid = {
        "workflow_name": "aid-pdn-multi2", "s3_path": "s3://bucket-pdn-multi2/resultados",
        "use_case": "caso_multi2",
        "workflow_variables": {"tecnologia": "AID"},
        "workflow_definition": [
            {"STEP_NAME": "step1", "TYPE": "topic", "LAST_STEP": "False"},
            {"STEP_NAME": "step2", "TYPE": "event", "LAST_STEP": "False"},
        ],
    }
    udz = {"item": {
        "id": "aid-pdn-multi2", "s3_path": "s3://bucket-pdn-multi2/resultados",
        "require_transmission": "true", "emit_event": "false",
    }}
    hu_folder = _escribir_hu_minima(tmp_path, ta, aid, udz, "DESPLIEGUE")

    r = appmod.analizar_hu(hu_folder)

    assert len(r["validaciones"]["aid_type_topic"]["types"]) == 2
    assert r["validaciones"]["aid_type_topic"]["ok"] is False, (
        "si CUALQUIER step tiene TYPE distinto de 'topic', la validación debe fallar"
    )


def test_aid_type_write_results_es_una_excepcion_valida(appmod, tmp_path):
    """Regresión de un caso real: un step final que solo escribe/guarda resultados
    (no publica evento) usa TYPE='write_results' en vez de 'topic', y eso es válido
    — no debe hacer fallar la validación (ver core.config.AID_TYPE_VALIDOS)."""
    ta = {
        "cu_name": "caso_writer", "type": "prompts",
        "kafka_output_topic": appmod.KAFKA_TOPIC_REQUERIDO,
    }
    aid = {
        "workflow_name": "aid-pdn-writer", "s3_path": "s3://bucket-pdn-writer/resultados",
        "use_case": "caso_writer",
        "workflow_variables": {"tecnologia": "AID"},
        "workflow_definition": [
            {"STEP_NAME": "extract", "TYPE": "topic", "LAST_STEP": "False"},
            {"STEP_NAME": "store_results", "TYPE": "write_results", "LAST_STEP": "False"},
        ],
    }
    udz = {"item": {
        "id": "aid-pdn-writer", "s3_path": "s3://bucket-pdn-writer/resultados",
        "require_transmission": "true", "emit_event": "false",
    }}
    hu_folder = _escribir_hu_minima(tmp_path, ta, aid, udz, "DESPLIEGUE")

    r = appmod.analizar_hu(hu_folder)

    assert r["validaciones"]["aid_type_topic"]["ok"] is True, (
        "TYPE='write_results' en un step final es una excepción válida, no debe marcar error"
    )


#  Regresión: ZIPs armados en Mac traen "._archivo.json" (metadata fantasma)

def test_buscar_archivos_ignora_archivos_fantasma_de_mac(appmod, tmp_path):
    """Un ZIP comprimido en Mac agrega, junto a cada archivo real, una copia
    oculta con metadata (resource fork) prefijada '._' — no debe detectarse
    como un TA/AID/UDZ real, ni contarse entre los archivos disponibles."""
    hu_folder = tmp_path / "hu-mac"
    adj = hu_folder / "adjuntos"
    adj.mkdir(parents=True)
    (adj / "ta_pia_demo.json").write_text('{"cu_name": "x"}', encoding="utf-8")
    (adj / "._ta_pia_demo.json").write_text("basura binaria de macOS", encoding="utf-8")

    arcs = appmod.buscar_archivos(hu_folder)

    assert arcs["ta"].name == "ta_pia_demo.json"
    assert len(arcs["ta_files"]) == 1


#  Regresión: DESPLIEGUE sin TA/AID/UDZ mostraba "12 correctas" en vez de INCOMPLETO

def test_despliegue_sin_archivos_queda_incompleto_y_no_12_correctas(appmod, tmp_path):
    """Bug reportado: cuando a un DESPLIEGUE le faltan TA/AID/UDZ, analizar_hu
    cortaba temprano con "validaciones": {} — la UI, al no encontrar cada
    clave, usaba el default ok=True y mostraba "12 correctas" aunque en
    realidad no se validó nada. Ahora el análisis sigue de largo y calcula
    las 12 validaciones igual (quedan en error, no vacías), y el estado
    general sigue siendo INCOMPLETO."""
    hu = tmp_path / "9002-hu-sin-archivos"
    (hu / "adjuntos").mkdir(parents=True)
    (hu / "metadata.json").write_text(json.dumps({
        "id": 9002, "title": "HU sin adjuntos", "state": "Active",
        "tipo_cambio": "DESPLIEGUE", "downloaded_at": "2026-01-01T00:00:00",
        "attachments": [],
    }), encoding="utf-8")

    r = appmod.analizar_hu(hu)

    assert r["estado_code"] == appmod.ESTADO_INCOMPLETO
    # La clave del bug: "validaciones" no debe quedar vacía.
    assert r["validaciones"] != {}
    n_ok = sum(
        1 for k in appmod.VALIDATION_KEYS
        if not r["validaciones"].get(k, {}).get("na", False) and appmod._val_ok(r["validaciones"].get(k, {}))
    )
    assert n_ok < len(appmod.VALIDATION_KEYS), (
        f"con TA/AID/UDZ faltantes no puede haber {n_ok}/{len(appmod.VALIDATION_KEYS)} validaciones 'correctas'"
    )
