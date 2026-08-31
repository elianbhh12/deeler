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


#  Regresión: DynamoDB no acepta float de Python, solo Decimal

def test_subir_componente_convierte_floats_a_decimal(tmp_path, monkeypatch):
    """DynamoDB (boto3) rechaza el tipo float nativo de Python con
    'Float types are not supported. Use Decimal types instead.' — cualquier
    número con punto decimal en el JSON (ej. un TA con "peso": 1.5) debe
    llegar a put_item como Decimal, no como float."""
    import sys
    import types
    from decimal import Decimal

    archivo = tmp_path / "ta_con_float.json"
    archivo.write_text(json.dumps({"cu_name": "caso_x", "peso": 1.5}), encoding="utf-8")

    item_capturado = {}

    class FakeTable:
        def put_item(self, Item):
            item_capturado.update(Item)

        def get_item(self, Key):
            return {"Item": item_capturado}

        key_schema = [{"AttributeName": "cu_name"}]

    class FakeDynamoResource:
        def Table(self, nombre):
            return FakeTable()

    class FakeSTS:
        def get_caller_identity(self):
            return {"Account": "123", "Arn": "arn:aws:iam::123:user/test"}

    class FakeSession:
        def __init__(self, **kwargs):
            pass

        def client(self, nombre, verify=None):
            return FakeSTS()

        def resource(self, nombre, verify=None):
            return FakeDynamoResource()

    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.Session = FakeSession

    fake_botocore = types.ModuleType("botocore")
    fake_botocore_exceptions = types.ModuleType("botocore.exceptions")
    fake_botocore_exceptions.ClientError = type("ClientError", (Exception,), {})
    fake_botocore_exceptions.NoCredentialsError = type("NoCredentialsError", (Exception,), {})
    fake_botocore_exceptions.EndpointConnectionError = type("EndpointConnectionError", (Exception,), {})

    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setitem(sys.modules, "botocore", fake_botocore)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", fake_botocore_exceptions)

    creds_path = tmp_path / "creds.json"
    creds_path.write_text(json.dumps({
        "aws_access_key_id": "AKIA123", "aws_secret_access_key": "x", "region_name": "us-east-1",
    }), encoding="utf-8")
    monkeypatch.setattr(aws_upload, "AWS_CRED_FILE", str(creds_path))

    resultado = aws_upload.subir_componente("ta", archivo, ambiente="qa")

    assert resultado["ok"] is True, resultado["log"]
    assert isinstance(item_capturado["peso"], Decimal)
    assert not isinstance(item_capturado["peso"], float)
