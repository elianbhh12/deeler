"""
Manejo de credenciales y sesion de AWS.

Mejora clave respecto al bash original: el script viejo SOLO aceptaba
credenciales puestas a mano en AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY /
AWS_SESSION_TOKEN, tecleando 3 `export` cada vez. Aqui hay tres formas,
de mas a menos comoda:
  1. --credenciales-file <archivo>: pegas UNA vez el bloque que te da el
     portal/consola de AWS (con `export AWS_...=...` o `AWS_...=...`) en
     un .txt, y el script lo lee solo. Cuando las credenciales expiren,
     solo actualizas ese archivo, sin tocar la terminal.
  2. --perfil <nombre>: perfil de ~/.aws/credentials o ~/.aws/config
     (incluye AWS SSO: `aws sso login --profile x`, que se auto-renueva).
  3. Variables de entorno ya exportadas en la terminal (comportamiento
     original).

Verificacion TLS: en la red del banco, la conexion a AWS pasa por un
proxy/firewall que reemplaza el certificado y rompe la verificacion TLS
normal de boto3 (mismo problema que ya se resolvio en el proyecto
hermano banco/core/aws_upload.py). Por eso VERIFY_TLS esta en False por
defecto -- si el dia de manana el banco instala su CA corporativa en el
almacen de certificados de Python, se puede volver a poner en True aqui,
en un solo lugar.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import boto3

logger = logging.getLogger(__name__)

VERIFY_TLS = False

_CRED_VARS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
_LINE_RE = re.compile(r'^(?:export\s+)?(AWS_[A-Z_]+)\s*=\s*"?([^"\n]*)"?\s*$')

# Alias aceptados en un archivo JSON de credenciales (minusculas, con o sin
# el prefijo "aws_"), para poder pegar tal cual lo que entrega el portal.
_JSON_KEY_ALIASES = {
    "aws_access_key_id": "AWS_ACCESS_KEY_ID",
    "access_key_id": "AWS_ACCESS_KEY_ID",
    "accesskeyid": "AWS_ACCESS_KEY_ID",
    "aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
    "secret_access_key": "AWS_SECRET_ACCESS_KEY",
    "secretaccesskey": "AWS_SECRET_ACCESS_KEY",
    "aws_session_token": "AWS_SESSION_TOKEN",
    "session_token": "AWS_SESSION_TOKEN",
    "sessiontoken": "AWS_SESSION_TOKEN",
}


class CredentialsError(RuntimeError):
    pass


def _load_credentials_json(path: Path) -> list[str]:
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CredentialsError(f"El archivo {path} no es un JSON valido: {exc}") from exc

    loaded = []
    for raw_key, value in data.items():
        env_key = _JSON_KEY_ALIASES.get(raw_key.strip().lower())
        if env_key and value:
            os.environ[env_key] = str(value)
            loaded.append(env_key)
    return loaded


def _load_credentials_text(path: Path) -> list[str]:
    loaded = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_RE.match(line)
        if match:
            key, value = match.group(1), match.group(2).strip()
            if key in _CRED_VARS and value:
                os.environ[key] = value
                loaded.append(key)
    return loaded


def load_credentials_file(path: Path) -> None:
    """Carga credenciales de AWS desde un archivo, para no tener que
    pegarlas a mano en la terminal cada vez que expiran. Acepta:
      - JSON: {"aws_access_key_id": "...", "aws_secret_access_key": "...",
               "aws_session_token": "..." (opcional)}
      - Texto: lineas `export AWS_ACCESS_KEY_ID="..."` (con o sin 'export'
        y sin comillas tambien funciona).
    El session token es opcional: una access key de usuario IAM permanente
    no lo trae."""
    if not path.exists():
        raise CredentialsError(f"No existe el archivo de credenciales: {path}")

    if path.suffix.lower() == ".json":
        loaded = _load_credentials_json(path)
    else:
        loaded = _load_credentials_text(path)

    missing = [v for v in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") if v not in loaded]
    if missing:
        raise CredentialsError(
            f"El archivo {path} no trae {', '.join(missing)}. "
            "Copia el bloque completo que te da el portal/consola de AWS."
        )
    logger.info("Credenciales cargadas desde %s (%s)", path, ", ".join(loaded))


def _import_boto3():
    # Import perezoso: asi los comandos que no tocan AWS (comparar,
    # verificar, agrupar, validar-nuevos) no requieren boto3 instalado.
    try:
        import boto3
        import urllib3
        from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError, ProfileNotFound
    except ImportError as exc:
        raise CredentialsError(
            "Falta boto3. Instala dependencias con: pip install -r requirements.txt"
        ) from exc
    if not VERIFY_TLS:
        # Con verify=False, urllib3 avisa en cada llamada que la conexion
        # no es segura; se silencia porque es intencional (ver docstring).
        urllib3.disable_warnings()
    return boto3, ClientError, EndpointConnectionError, NoCredentialsError, ProfileNotFound


def build_session(profile: Optional[str] = None, region: str = "us-east-1") -> "boto3.Session":
    boto3, _, _, _, ProfileNotFound = _import_boto3()
    try:
        if profile:
            return boto3.Session(profile_name=profile, region_name=region)
        return boto3.Session(region_name=region)
    except ProfileNotFound as exc:
        raise CredentialsError(
            f"El perfil de AWS '{profile}' no existe en ~/.aws/config o ~/.aws/credentials."
        ) from exc


def validate_credentials(session: "boto3.Session") -> dict:
    """Confirma que las credenciales actuales son validas y no expiraron,
    igual que hacia `aws sts get-caller-identity` en el bash original,
    pero con un mensaje de error mas util."""
    _, ClientError, EndpointConnectionError, NoCredentialsError, _ = _import_boto3()
    try:
        sts = session.client("sts", verify=VERIFY_TLS)
        identity = sts.get_caller_identity()
    except NoCredentialsError as exc:
        raise CredentialsError(
            "No hay credenciales de AWS disponibles. Exporta "
            "AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_SESSION_TOKEN, "
            "o usa --perfil <nombre> con un perfil configurado (aws configure / aws sso login)."
        ) from exc
    except EndpointConnectionError as exc:
        raise CredentialsError(
            f"No se pudo conectar a AWS STS (¿estas en la red del banco?): {exc}"
        ) from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("ExpiredToken", "ExpiredTokenException", "UnrecognizedClientException"):
            raise CredentialsError(
                "Las credenciales de AWS expiraron o son invalidas. Vuelve a "
                "autenticarte (nuevo login SSO o nuevas credenciales temporales) e intenta de nuevo."
            ) from exc
        raise CredentialsError(f"Error validando credenciales AWS: {exc}") from exc

    logger.info(
        "Credenciales validas. Cuenta=%s, Usuario/Rol=%s",
        identity.get("Account"), identity.get("Arn"),
    )
    return identity
