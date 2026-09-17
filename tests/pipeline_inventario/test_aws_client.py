import json
import os

import pytest

from python_pipeline.aws_client import CredentialsError, load_credentials_file

_VARS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")


@pytest.fixture(autouse=True)
def _clean_env():
    saved = {k: os.environ.pop(k, None) for k in _VARS}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def test_carga_json_sin_session_token(tmp_path):
    cred_file = tmp_path / "aws_credentials.json"
    cred_file.write_text(json.dumps({
        "aws_access_key_id": "AKIA_TEST",
        "aws_secret_access_key": "secreto_test",
        "region_name": "us-east-1",
    }), encoding="utf-8")

    load_credentials_file(cred_file)

    assert os.environ["AWS_ACCESS_KEY_ID"] == "AKIA_TEST"
    assert os.environ["AWS_SECRET_ACCESS_KEY"] == "secreto_test"
    assert "AWS_SESSION_TOKEN" not in os.environ


def test_carga_json_con_session_token(tmp_path):
    cred_file = tmp_path / "creds.json"
    cred_file.write_text(json.dumps({
        "AccessKeyId": "ASIA_TEST",
        "SecretAccessKey": "secreto2",
        "SessionToken": "token123",
    }), encoding="utf-8")

    load_credentials_file(cred_file)

    assert os.environ["AWS_ACCESS_KEY_ID"] == "ASIA_TEST"
    assert os.environ["AWS_SESSION_TOKEN"] == "token123"


def test_carga_texto_con_export(tmp_path):
    cred_file = tmp_path / "creds.txt"
    cred_file.write_text(
        'export AWS_ACCESS_KEY_ID="ASIA_X"\n'
        'export AWS_SECRET_ACCESS_KEY="sec_x"\n'
        'export AWS_SESSION_TOKEN="tok_x"\n',
        encoding="utf-8",
    )

    load_credentials_file(cred_file)

    assert os.environ["AWS_ACCESS_KEY_ID"] == "ASIA_X"
    assert os.environ["AWS_SESSION_TOKEN"] == "tok_x"


def test_archivo_incompleto_lanza_error_claro(tmp_path):
    cred_file = tmp_path / "creds.json"
    cred_file.write_text(json.dumps({"aws_access_key_id": "AKIA_X"}), encoding="utf-8")

    with pytest.raises(CredentialsError, match="AWS_SECRET_ACCESS_KEY"):
        load_credentials_file(cred_file)


def test_archivo_inexistente(tmp_path):
    with pytest.raises(CredentialsError):
        load_credentials_file(tmp_path / "no_existe.json")
