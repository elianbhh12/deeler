from python_pipeline import common


def test_normalize_text_quita_tildes_y_simbolos():
    assert common.normalize_text("Carta-Notificación #1") == "carta notificacion 1"


def test_normalize_text_vacio():
    assert common.normalize_text(None) == ""
    assert common.normalize_text("") == ""


def test_sanitize_filename_reemplaza_caracteres_problematicos():
    assert common.sanitize_filename("a/b:c d?e*f\"g<h>i|j") == "a_b_c_defghij"


def test_sanitize_csv_field_neutraliza_separador_y_saltos():
    assert common.sanitize_csv_field("a;b\nc\rd") == "a,b c d"
    assert common.sanitize_csv_field(None) == ""


def test_find_key_recursive_encuentra_en_anidados():
    data = {"a": {"b": [{"c": {"target": "valor"}}]}}
    assert common.find_key_recursive(data, "target") == "valor"


def test_find_key_recursive_ausente():
    assert common.find_key_recursive({"a": 1}, "no_existe") is None


def test_get_use_case_busca_step_variables_anidado():
    data = {"pasos": [{"STEP_VARIABLES": {"use_case": "ta_x"}}]}
    assert common.get_use_case(data) == "ta_x"


def test_get_use_case_vacio_si_no_hay_step_variables():
    assert common.get_use_case({"otra_cosa": 1}) == ""


def test_has_nested_key_true_y_false():
    assert common.has_nested_key({"a": {"use_case": "x"}}, "use_case") is True
    assert common.has_nested_key({"a": {"otro": "x"}}, "use_case") is False


def test_has_topic_step_detecta_type_topic():
    data = {
        "workflow_definition": [
            {"THREADS": [{"STEPS": [{"TYPE": "ms"}, {"TYPE": "topic"}]}]}
        ]
    }
    assert common.has_topic_step(data) is True


def test_has_topic_step_falso_sin_topic():
    data = {"workflow_definition": [{"THREADS": [{"STEPS": [{"TYPE": "ms"}]}]}]}
    assert common.has_topic_step(data) is False


def test_get_tipo_documento_prioriza_workflow_variables():
    data = {"workflow_variables": {"tipoDocumento": "carta"}, "tipoDocumento": "otro"}
    assert common.get_tipo_documento(data) == "carta"


def test_get_tipo_documento_default_si_no_existe():
    assert common.get_tipo_documento({}) == "SIN_TIPODOCUMENTO"


def test_get_proceso_default_si_no_existe():
    assert common.get_proceso({}) == "SIN_PROCESO"


def test_iter_json_files_directorio(tmp_path):
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")
    (tmp_path / "ignorar.txt").write_text("x", encoding="utf-8")

    found = sorted(common.basename(p) for p, _ in common.iter_json_files(str(tmp_path)))
    assert found == ["a.json", "b.json"]


def test_iter_json_files_zip(tmp_path):
    import zipfile

    zip_path = tmp_path / "datos.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("carpeta/a.json", "{\"k\": 1}")
        zf.writestr("carpeta/nota.txt", "no es json")

    results = list(common.iter_json_files(f"{zip_path}/carpeta"))
    assert len(results) == 1
    assert results[0][1] == '{"k": 1}'
