import json

import pytest

import core.aws_upload as aws_upload


#  cargar_credenciales_aws

def test_cargar_credenciales_archivo_inexistente_lanza(tmp_path):
    with pytest.raises(FileNotFoundError):
        aws_upload.cargar_credenciales_aws(tmp_path / "no_existe.json")


def test_cargar_credenciales_faltan_campos_lanza(tmp_path):
    ruta = tmp_path / "creds.json"
    ruta.write_text(json.dumps({"aws_access_key_id": "x"}), encoding="utf-8")
    with pytest.raises(ValueError):
        aws_upload.cargar_credenciales_aws(ruta)


def test_cargar_credenciales_session_token_es_opcional(tmp_path):
    """Un usuario IAM normal (access key permanente, ej. cuenta personal) no
    tiene aws_session_token — solo aplica a credenciales temporales STS
    (como usa el banco). No debe exigirse."""
    ruta = tmp_path / "creds.json"
    ruta.write_text(json.dumps({
        "aws_access_key_id": "AKIA123",
        "aws_secret_access_key": "secreto",
        "region_name": "us-east-1",
    }), encoding="utf-8")
    creds = aws_upload.cargar_credenciales_aws(ruta)
    assert "aws_session_token" not in creds
    assert creds["aws_access_key_id"] == "AKIA123"


def test_cargar_credenciales_incluye_session_token_si_viene(tmp_path):
    ruta = tmp_path / "creds.json"
    ruta.write_text(json.dumps({
        "aws_access_key_id": "AKIA123",
        "aws_secret_access_key": "secreto",
        "aws_session_token": "token-temporal",
        "region_name": "us-east-1",
    }), encoding="utf-8")
    creds = aws_upload.cargar_credenciales_aws(ruta)
    assert creds["aws_session_token"] == "token-temporal"


#  subir_componente — solo los caminos que no requieren AWS real

def test_subir_componente_tipo_o_ambiente_sin_tabla_configurada(tmp_path):
    archivo = tmp_path / "ta_x.json"
    archivo.write_text("{}", encoding="utf-8")
    resultado = aws_upload.subir_componente("ta", archivo, ambiente="ambiente_inexistente")
    assert resultado["ok"] is False
    assert any("no hay tabla configurada" in linea for linea in resultado["log"])


def test_subir_componente_archivo_no_existe(tmp_path):
    resultado = aws_upload.subir_componente("ta", tmp_path / "no_existe.json", ambiente="qa")
    assert resultado["ok"] is False
    assert any("no se encontró el archivo" in linea for linea in resultado["log"])


def test_subir_componente_json_invalido(tmp_path):
    archivo = tmp_path / "ta_roto.json"
    archivo.write_text("{esto no es json", encoding="utf-8")
    resultado = aws_upload.subir_componente("ta", archivo, ambiente="qa")
    assert resultado["ok"] is False
    assert any("no es válido" in linea for linea in resultado["log"])


def test_subir_componente_log_incluye_tabla_destino(tmp_path, monkeypatch):
    """No debe intentar conectarse a AWS de verdad: se fuerza AWS_CRED_FILE a
    una ruta inexistente para que, tenga boto3 instalado o no el entorno que
    corre el test, la función corte antes de cualquier llamada de red — el
    repo puede tener un aws_credentials.json real en la raíz (gitignored) y
    el test nunca debe depender de eso ni intentar usarlo."""
    monkeypatch.setattr(aws_upload, "AWS_CRED_FILE", str(tmp_path / "creds_que_no_existen.json"))
    archivo = tmp_path / "ta_x.json"
    archivo.write_text(json.dumps({"cu_name": "caso_x"}), encoding="utf-8")
    resultado = aws_upload.subir_componente("ta", archivo, ambiente="qa")
    tabla_esperada = aws_upload.AWS_TABLAS["qa"]["ta"]
    assert any(tabla_esperada in linea for linea in resultado["log"])
    assert resultado["ok"] is False
