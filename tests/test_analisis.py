import json
from pathlib import Path

import pytest

import core.analysis as analysis


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
    ("s3://bucket-pdn/resultados", "PDN"),  # sin guion al final del token
    ("s3://bucket-dev-x/resultados", "DESCONOCIDO"),  # solo existen PDN y QA
    ("s3://bucket-uat-x/resultados", "DESCONOCIDO"),
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
    out_zone_ok/copiar_ok), así que .get('ok', True) siempre devolvía True.

    La regla real es solo copiarResultadoBucket=true — out_zone no forma
    parte de ella (ni bloquea ni hace falta), así que este caso (falta
    copiarResultadoBucket) sigue dando error igual con o sin out_zone."""
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
            # falta copiarResultadoBucket -> debe ser error
        }],
    }
    udz = {"item": {
        "id": "aid-pdn-test", "s3_path": "s3://bucket-pdn-test/resultados",
        "require_transmission": "true", "emit_event": "false",
    }}
    hu_folder = _escribir_hu_minima(tmp_path, ta, aid, udz, "DESPLIEGUE")

    r = appmod.analizar_hu(hu_folder)

    assert r["validaciones"]["out_zone_copiar"]["copiar_ok"] is False
    assert r["estado_code"] == appmod.ESTADO_ERROR, (
        "falta de copiarResultadoBucket=True debe bloquear el estado LISTO"
    )


def test_out_zone_junto_con_copiar_bucket_true_ya_no_es_error(appmod, tmp_path):
    """out_zone no es parte de la regla: que aparezca junto con
    copiarResultadoBucket=true no debe dar error (antes se trataba como
    conflicto)."""
    ta = {
        "cu_name": "caso_test2", "type": "prompts",
        "kafka_output_topic": "documentreceivingmanagement.documentuploadedv1",
    }
    aid = {
        "workflow_name": "aid-pdn-test2", "s3_path": "s3://bucket-pdn-test2/resultados",
        "use_case": "caso_test2", "TYPE": "topic",
        "workflow_variables": {"tecnologia": "AID"},
        "workflow_definition": [{
            "STEP_NAME": "step1", "FUNCTION_NAME": "call_api", "LAST_STEP": "False",
            "STEP_VARIABLES": {
                "JOB_NAME": "job1", "out_zone": "s3://bucket-pdn-test2/out/",
                "copiarResultadoBucket": "true",
            },
        }],
    }
    udz = {"item": {
        "id": "aid-pdn-test2", "s3_path": "s3://bucket-pdn-test2/resultados",
        "require_transmission": "true", "emit_event": "false",
    }}
    hu_folder = _escribir_hu_minima(tmp_path, ta, aid, udz, "DESPLIEGUE")

    r = appmod.analizar_hu(hu_folder)

    assert r["validaciones"]["out_zone_copiar"]["copiar_ok"] is True
    assert r["estado_code"] == appmod.ESTADO_LISTO


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


#  Regresión: cargar_json no debe reventar con una ruta larga/inexistente

def test_cargar_json_ruta_inexistente_no_revienta(appmod, tmp_path):
    """En Windows, una ruta de más de ~260 caracteres da el mismo error que
    un archivo inexistente — cargar_json debe manejar ambos casos sin tirar
    una excepción, devolviendo None."""
    corta = tmp_path / "no_existe.json"
    assert appmod.cargar_json(corta) is None

    ruta_larga = tmp_path / ("x" * 250 + ".json")
    assert appmod.cargar_json(ruta_larga) is None


#  UDZ Crudos + Resultados como archivos separados: cada uno con su propia
#  validación (no solo el "activo") — ver core.analysis._validar_udz_cruzadas
#  y detectar_slots_udz, y el bug reportado: la consola de "Subir a AWS" no
#  dejaba subir los 4 componentes (TA, AID, UDZ Crudos, UDZ Resultados) sin
#  antes elegir cada UDZ como activo uno por uno.

def _escribir_hu_dos_udz(base: Path, ta: dict, aid: dict, udz_crudos: dict, udz_resultados: dict,
                          tipo_cambio: str = "DESPLIEGUE") -> Path:
    hu = base / "9003-hu-test-dos-udz"
    adj = hu / "adjuntos"
    adj.mkdir(parents=True, exist_ok=True)
    (hu / "metadata.json").write_text(json.dumps({
        "id": 9003, "title": "HU de prueba — dos UDZ", "state": "Active",
        "tipo_cambio": tipo_cambio, "downloaded_at": "2026-01-01T00:00:00",
        "attachments": [],
    }), encoding="utf-8")
    (adj / "ta_test.json").write_text(json.dumps(ta), encoding="utf-8")
    (adj / "aid_test.json").write_text(json.dumps(aid), encoding="utf-8")
    (adj / "udz_crudos.json").write_text(json.dumps(udz_crudos), encoding="utf-8")
    (adj / "udz_resultados.json").write_text(json.dumps(udz_resultados), encoding="utf-8")
    return hu


def _hu_dos_udz_bien_armada(tmp_path: Path) -> dict:
    ta = {
        "cu_name": "caso_dos_udz", "type": "prompts",
        "kafka_output_topic": "documentreceivingmanagement.documentuploadedv1",
    }
    aid = {
        "workflow_name": "aid-pdn-dosudz", "s3_path": "s3://bucket-pdn-dosudz/crudos/algo",
        "use_case": "caso_dos_udz", "TYPE": "topic",
        "workflow_variables": {"tecnologia": "AID"},
        "workflow_definition": [{"STEP_NAME": "step1", "TYPE": "topic", "LAST_STEP": "False"}],
    }
    # CRUDOS (entrada): s3_path IDÉNTICO al de AID.
    udz_crudos = {"item": {
        "id": "aid-pdn-dosudz", "s3_path": "s3://bucket-pdn-dosudz/crudos/algo",
        "require_transmission": "false", "emit_event": "true",
    }}
    # RESULTADOS (salida/transmisión): mismo path que AID pero con "crudos" -> "resultados".
    udz_resultados = {"item": {
        "id": "aid-pdn-dosudz", "s3_path": "s3://bucket-pdn-dosudz/resultados/algo",
        "require_transmission": "true", "emit_event": "false",
    }}
    hu_folder = _escribir_hu_dos_udz(tmp_path, ta, aid, udz_crudos, udz_resultados)
    return analysis.analizar_hu(hu_folder)


def test_detectar_slots_udz_devuelve_dos_cuando_hay_crudos_y_resultados(appmod, tmp_path):
    r = _hu_dos_udz_bien_armada(tmp_path)
    slots = appmod.detectar_slots_udz(r)
    assert {s["tipo"] for s in slots} == {"CRUDOS", "RESULTADOS"}
    assert sum(1 for s in slots if s["es_activo"]) == 1, "solo uno de los dos debe quedar como activo"


def test_udz_no_activo_queda_validado_por_separado(appmod, tmp_path):
    """El bug reportado: sin esto, el UDZ que no está 'activo' (elegido en el
    selector 'UDZ a usar') no tenía ninguna validación propia, y la consola
    de AWS no dejaba subirlo sin antes cambiar el selector. Ahora
    'validaciones_udz_extra' trae, para el otro archivo, las mismas 4
    validaciones cruzadas que el activo tiene en 'validaciones'."""
    r = _hu_dos_udz_bien_armada(tmp_path)

    assert "validaciones_udz_extra" in r
    assert len(r["validaciones_udz_extra"]) == 1, "un solo slot queda 'extra' (el que no es el activo)"

    _clave_extra = next(iter(r["validaciones_udz_extra"]))
    assert _clave_extra in ("udz_crudos", "udz_resultados")
    _val_extra = r["validaciones_udz_extra"][_clave_extra]

    for _campo in ("s3_path", "workflow_vs_id", "ambiente_workflow_id", "udz_transmisiones"):
        assert _campo in _val_extra, f"falta '{_campo}' en la validación del UDZ no-activo"
        assert _val_extra[_campo]["ok"] is True, (
            f"'{_campo}' del UDZ no-activo debería dar OK con esta HU bien armada — {_val_extra[_campo]}"
        )

    # Y el activo (en "validaciones", el lugar de siempre) también OK.
    for _campo in ("s3_path", "workflow_vs_id", "ambiente_workflow_id", "udz_transmisiones"):
        assert r["validaciones"][_campo]["ok"] is True, (
            f"'{_campo}' del UDZ activo debería dar OK con esta HU bien armada — {r['validaciones'][_campo]}"
        )


def test_udz_resultados_s3_path_no_exige_igualdad_estricta_con_aid(appmod, tmp_path):
    """RESULTADOS es la excepción: su s3_path no es igual al de AID a
    propósito ("crudos" -> "resultados" en el mismo lugar de la ruta) — la
    prueba de arriba ya lo confirma indirectamente, esta lo deja explícito."""
    r = _hu_dos_udz_bien_armada(tmp_path)
    slots = {s["tipo"]: s for s in appmod.detectar_slots_udz(r)}
    resultados_activo = slots["RESULTADOS"]["es_activo"]

    val_resultados = (
        r["validaciones"] if resultados_activo
        else r["validaciones_udz_extra"]["udz_resultados"]
    )
    assert val_resultados["s3_path"]["udz"] != val_resultados["s3_path"]["aid"], (
        "el s3_path de RESULTADOS no debería ser idéntico al de AID"
    )
    assert val_resultados["s3_path"]["ok"] is True


def test_udz_con_un_solo_archivo_no_genera_validaciones_extra(appmod, tmp_path):
    """Backward-compat: con un solo UDZ (el caso normal, sin split
    crudos/resultados) no debe aparecer 'validaciones_udz_extra' — el
    comportamiento de siempre no cambia."""
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

    assert "validaciones_udz_extra" not in r


#  Regresión: subir un componente a QA después de subirlo a PDN no debe
#  borrar el estado de "ya desplegado en PDN" (los dos ambientes se registran
#  por separado, no se pisan entre sí — ver ui.aws_console._persistir_subida_aws)

def test_obtener_estado_pdn_real_con_registro_por_ambiente(appmod):
    r = {
        "ta_activo": "ta.json", "aid_activo": "aid.json", "udz_files": [],
        "ta_aws_pdn_por": "ana", "ta_aws_pdn_en": "2026-01-01T10:00:00",
        "aid_aws_pdn_por": "ana", "aid_aws_pdn_en": "2026-01-01T10:01:00",
        "udz_aws_pdn_por": "ana", "udz_aws_pdn_en": "2026-01-01T10:02:00",
        # Actividad más reciente: el mismo TA se volvió a subir a QA después.
        "ta_aws_ambiente": "qa", "ta_aws_por": "ana", "ta_aws_en": "2026-02-01T09:00:00",
    }
    estado = appmod.obtener_estado_pdn_real(r)
    assert estado["desplegado"] is True, "una subida posterior a QA no debe borrar el estado de PDN"
    assert estado["por"] == "ana"


def test_obtener_estado_pdn_real_compatibilidad_con_registro_viejo(appmod):
    """Análisis guardados antes de separar el registro por ambiente solo
    tienen el campo plano '_aws_ambiente' — debe seguir funcionando mientras
    ese componente no se haya vuelto a subir a otro ambiente desde entonces."""
    r = {
        "ta_activo": "ta.json", "aid_activo": None, "udz_files": [],
        "ta_aws_ambiente": "pdn", "ta_aws_por": "ana", "ta_aws_en": "2026-01-01T10:00:00",
    }
    estado = appmod.obtener_estado_pdn_real(r)
    assert estado["desplegado"] is True
    assert estado["por"] == "ana"


def test_obtener_estado_pdn_real_qa_sin_pdn_previo_no_desplegado(appmod):
    r = {
        "ta_activo": "ta.json", "aid_activo": None, "udz_files": [],
        "ta_aws_ambiente": "qa", "ta_aws_por": "ana", "ta_aws_en": "2026-01-01T10:00:00",
    }
    estado = appmod.obtener_estado_pdn_real(r)
    assert estado["desplegado"] is False


#  Regresión: udz_transmisiones no validaba nada real cuando require_transmission
#  no era literalmente "true" — un UDZ de RESULTADOS (por s3_path) mal configurado
#  con require_transmission=false pasaba como "NO_DEFINIDO" -> ok=True sin alertar,
#  y un CRUDOS con emit_event mal puesto tampoco se detectaba.

def _hu_udz_transmisiones(tmp_path: Path, udz_extra: dict) -> dict:
    ta = {
        "cu_name": "caso_tx", "type": "prompts",
        "kafka_output_topic": "documentreceivingmanagement.documentuploadedv1",
    }
    aid = {
        "workflow_name": "aid-pdn-tx", "s3_path": "s3://bucket-pdn-tx/crudos/algo",
        "use_case": "caso_tx", "TYPE": "topic",
        "workflow_variables": {"tecnologia": "AID"},
        "workflow_definition": [{"STEP_NAME": "step1", "TYPE": "topic", "LAST_STEP": "False"}],
    }
    udz = {"item": {"id": "aid-pdn-tx", **udz_extra}}
    hu_folder = _escribir_hu_minima(tmp_path, ta, aid, udz, "DESPLIEGUE")
    return analysis.analizar_hu(hu_folder)


def test_udz_resultados_por_s3_path_con_require_transmission_false_da_error(appmod, tmp_path):
    """UDZ clasificado RESULTADOS por su s3_path, pero con require_transmission
    en false (mal configurado) — antes esto quedaba como 'NO_DEFINIDO' y pasaba
    en silencio; ahora debe marcar error."""
    r = _hu_udz_transmisiones(tmp_path, {
        "s3_path": "s3://bucket-pdn-tx/resultados/algo",
        "require_transmission": "false", "emit_event": "true",
    })
    assert r["validaciones"]["udz_transmisiones"]["udz_tipo"] == "RESULTADOS"
    assert r["validaciones"]["udz_transmisiones"]["ok"] is False


def test_udz_crudos_con_emit_event_mal_puesto_da_error(appmod, tmp_path):
    """UDZ clasificado CRUDOS por su s3_path, pero con emit_event=false (debería
    ser true) — antes esto pasaba sin validar nada; ahora debe marcar error."""
    r = _hu_udz_transmisiones(tmp_path, {
        "s3_path": "s3://bucket-pdn-tx/crudos/algo",
        "require_transmission": "false", "emit_event": "false",
    })
    assert r["validaciones"]["udz_transmisiones"]["udz_tipo"] == "CRUDOS"
    assert r["validaciones"]["udz_transmisiones"]["ok"] is False


def test_udz_crudos_bien_configurado_sigue_dando_ok(appmod, tmp_path):
    r = _hu_udz_transmisiones(tmp_path, {
        "s3_path": "s3://bucket-pdn-tx/crudos/algo",
        "require_transmission": "false", "emit_event": "true",
    })
    assert r["validaciones"]["udz_transmisiones"]["udz_tipo"] == "CRUDOS"
    assert r["validaciones"]["udz_transmisiones"]["ok"] is True


def test_udz_no_clasificable_en_despliegue_da_error(appmod, tmp_path):
    """Un UDZ presente pero que no se puede clasificar ni por s3_path
    ('crudos'/'resultados') ni por require_transmission=true queda
    'DESCONOCIDO' — en un DESPLIEGUE eso es un error real (antes de este
    fix pasaba siempre en verde sin validar nada), en una MODIFICACIÓN
    sigue sin bloquear."""
    r = _hu_udz_transmisiones(tmp_path, {
        "s3_path": "s3://bucket-pdn-tx/miscelaneo/algo",
        "require_transmission": "false", "emit_event": "false",
    })
    assert r["validaciones"]["udz_transmisiones"]["udz_tipo"] == "DESCONOCIDO"
    assert r["validaciones"]["udz_transmisiones"]["ok"] is False


#  Regresión: con UDZ separado en Crudos+Resultados, un error en el archivo
#  NO activo debe bloquear igual el estado general — antes solo el UDZ
#  activo entraba en el cálculo de LISTO/ERROR, y el otro podía estar mal
#  configurado (ej. emit_event al revés) sin que nadie lo viera hasta
#  elegirlo a mano en el selector "UDZ a usar".

def test_udz_no_activo_con_error_bloquea_estado_general(appmod, tmp_path):
    ta = {
        "cu_name": "caso_dosudz2", "type": "prompts",
        "kafka_output_topic": appmod.KAFKA_TOPIC_REQUERIDO,
    }
    aid = {
        "workflow_name": "aid-pdn-dosudz2", "s3_path": "s3://bucket-pdn-dosudz2/crudos/algo",
        "use_case": "caso_dosudz2", "TYPE": "topic",
        "workflow_variables": {"tecnologia": "AID"},
        "workflow_definition": [{"STEP_NAME": "step1", "TYPE": "topic", "LAST_STEP": "False"}],
    }
    udz_crudos = {"item": {
        "id": "aid-pdn-dosudz2", "s3_path": "s3://bucket-pdn-dosudz2/crudos/algo",
        "require_transmission": "false", "emit_event": "true",
    }}
    # RESULTADOS mal configurado a propósito: emit_event debería ser "false".
    udz_resultados = {"item": {
        "id": "aid-pdn-dosudz2", "s3_path": "s3://bucket-pdn-dosudz2/resultados/algo",
        "require_transmission": "true", "emit_event": "true",
    }}
    hu_folder = _escribir_hu_dos_udz(tmp_path, ta, aid, udz_crudos, udz_resultados)

    # Se fuerza CRUDOS (bien armado) como activo — el error queda en el otro.
    _crudos_path = hu_folder / "adjuntos" / "udz_crudos.json"
    r = appmod.analizar_hu(hu_folder, udz_override=_crudos_path)

    assert r["validaciones"]["udz_transmisiones"]["ok"] is True, "el UDZ activo (crudos) está bien armado"
    assert "udz_resultados" in r.get("validaciones_udz_extra", {})
    assert r["validaciones_udz_extra"]["udz_resultados"]["udz_transmisiones"]["ok"] is False
    assert r["estado_code"] == appmod.ESTADO_ERROR, (
        "un error en el UDZ no activo (resultados) debe bloquear el estado LISTO igual"
    )
