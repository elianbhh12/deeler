"""Subida de TA/AID/UDZ a las tablas DynamoDB de QA/PDN.

Sube, por HU, exactamente el archivo que la herramienta validó. Siempre
intenta el envío real: si falta boto3, las credenciales, o no hay red, el
error real queda en el log en vez de esconderse.

`subir_componente` devuelve, además del resultado, un `log` paso a paso para
que la consola de la UI pueda mostrar el detalle completo de qué pasó.
"""
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .config import AWS_CRED_FILE, AWS_TABLAS


def cargar_credenciales_aws(ruta: Path) -> dict:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo de credenciales AWS: {ruta}")
    creds = json.loads(ruta.read_text(encoding="utf-8"))
    # aws_session_token solo es obligatorio con credenciales temporales (STS).
    requeridos = ["aws_access_key_id", "aws_secret_access_key", "region_name"]
    faltantes = [k for k in requeridos if not creds.get(k)]
    if faltantes:
        raise ValueError(f"Faltan campos en el archivo de credenciales AWS: {faltantes}")
    return {k: v for k, v in creds.items() if v}


def subir_componente(tipo: str, archivo: Path, ambiente: str = "qa") -> dict:
    """Sube el JSON de un componente (ta/aid/udz) a su tabla DynamoDB del
    ambiente indicado (qa/pdn). Devuelve {ok, tabla, archivo, log}."""
    log = []

    def _log(linea):
        log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {linea}")

    tabla = AWS_TABLAS.get(ambiente, {}).get(tipo)
    _log(f"Componente: {tipo.upper()}  ·  Ambiente: {ambiente.upper()}  ·  Tabla destino: {tabla or '(desconocida)'}")
    if not tabla:
        _log(f"ERROR: no hay tabla configurada para {tipo}/{ambiente}")
        return {"ok": False, "log": log}

    if not archivo or not Path(archivo).exists():
        _log(f"ERROR: no se encontró el archivo {tipo.upper()} a subir")
        return {"ok": False, "log": log}

    archivo = Path(archivo)
    _log(f"Archivo: {archivo.name}")
    try:
        # DynamoDB no acepta float, solo Decimal.
        item = json.loads(archivo.read_text(encoding="utf-8"), parse_float=Decimal)
        _log(f"JSON válido — {len(item)} campo(s) de primer nivel")
    except Exception as e:
        _log(f"ERROR: el JSON de {archivo.name} no es válido: {e}")
        return {"ok": False, "log": log}

    try:
        import boto3
        import urllib3
        from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError
        # verify=False es necesario en la red del banco; se silencia el warning que genera.
        urllib3.disable_warnings()
    except ImportError:
        _log("ERROR: falta instalar boto3 (pip install boto3)")
        return {"ok": False, "log": log}

    if not AWS_CRED_FILE:
        _log("ERROR: no hay AWS_CRED_FILE configurado en .env — falta la ruta al JSON de credenciales")
        return {"ok": False, "log": log}

    try:
        _log(f"Cargando credenciales desde: {AWS_CRED_FILE}")
        creds = cargar_credenciales_aws(Path(AWS_CRED_FILE))
    except Exception as e:
        _log(f"ERROR cargando credenciales AWS: {e}")
        return {"ok": False, "log": log}

    try:
        session = boto3.Session(**creds)
        sts = session.client("sts", verify=False)
        identity = sts.get_caller_identity()
        _log(f"Cuenta AWS: {identity.get('Account')}")
        _log(f"ARN: {identity.get('Arn')}")
    except NoCredentialsError:
        _log("ERROR: no hay credenciales AWS configuradas")
        return {"ok": False, "log": log}
    except EndpointConnectionError as e:
        _log(f"ERROR: no se pudo conectar a AWS STS (¿estás en la red del banco?): {e}")
        return {"ok": False, "log": log}
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        msg = e.response.get("Error", {}).get("Message", str(e))
        _log(f"ERROR: credenciales inválidas/expiradas ({code}): {msg}")
        return {"ok": False, "log": log}
    except Exception as e:
        _log(f"ERROR validando credenciales: {e}")
        return {"ok": False, "log": log}

    try:
        dynamodb = session.resource("dynamodb", verify=False)
        tabla_ref = dynamodb.Table(tabla)
        _log(f"Conectando a tabla: {tabla}")
        tabla_ref.put_item(Item=item)
        _log(f"put_item OK — {archivo.name} → {tabla}")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        msg = e.response.get("Error", {}).get("Message", str(e))
        _log(f"ERROR de AWS ({code}): {msg}")
        return {"ok": False, "log": log}
    except Exception as e:
        _log(f"ERROR subiendo a AWS: {e}")
        return {"ok": False, "log": log}

    # Releer el item para confirmar que realmente quedó guardado.
    try:
        pk_name = tabla_ref.key_schema[0]["AttributeName"]
        pk_valor = item.get(pk_name)
        if pk_valor is None:
            _log(f"AVISO: no se pudo verificar — el item no tiene la partition key '{pk_name}'")
        else:
            leido = tabla_ref.get_item(Key={pk_name: pk_valor}).get("Item")
            if leido:
                _log(f"Verificado: el item quedó guardado en {tabla} ({pk_name}='{pk_valor}')")
            else:
                _log(f"AVISO: se subió pero no se pudo releer el item ({pk_name}='{pk_valor}')")
    except Exception as e:
        _log(f"AVISO: no se pudo verificar la escritura (el put_item sí fue OK): {e}")

    return {"ok": True, "tabla": tabla, "archivo": archivo.name, "log": log}


def verificar_en_tabla(tipo: str, archivo: Path, ambiente: str = "pdn") -> dict:
    """Confirma si el item de este archivo ya existe en la tabla DynamoDB del
    ambiente indicado, SIN volver a subirlo (solo get_item). Sirve para
    recuperar el estado de "desplegado en PDN" cuando la trazabilidad local
    se perdió (ej. se pisó al subir el mismo componente a QA después) pero el
    dato real ya está en AWS. Devuelve {existe, tabla, log}."""
    log = []

    def _log(linea):
        log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {linea}")

    tabla = AWS_TABLAS.get(ambiente, {}).get(tipo)
    _log(f"Verificando: {tipo.upper()}  ·  Ambiente: {ambiente.upper()}  ·  Tabla: {tabla or '(desconocida)'}")
    if not tabla:
        _log(f"ERROR: no hay tabla configurada para {tipo}/{ambiente}")
        return {"existe": False, "log": log}

    if not archivo or not Path(archivo).exists():
        _log(f"ERROR: no se encontró el archivo {tipo.upper()} para verificar")
        return {"existe": False, "log": log}

    archivo = Path(archivo)
    try:
        item = json.loads(archivo.read_text(encoding="utf-8"), parse_float=Decimal)
    except Exception as e:
        _log(f"ERROR: el JSON de {archivo.name} no es válido: {e}")
        return {"existe": False, "log": log}

    try:
        import boto3
        import urllib3
        from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError
        urllib3.disable_warnings()
    except ImportError:
        _log("ERROR: falta instalar boto3 (pip install boto3)")
        return {"existe": False, "log": log}

    if not AWS_CRED_FILE:
        _log("ERROR: no hay AWS_CRED_FILE configurado en .env")
        return {"existe": False, "log": log}

    try:
        creds = cargar_credenciales_aws(Path(AWS_CRED_FILE))
        session = boto3.Session(**creds)
        dynamodb = session.resource("dynamodb", verify=False)
        tabla_ref = dynamodb.Table(tabla)
        pk_name = tabla_ref.key_schema[0]["AttributeName"]
        pk_valor = item.get(pk_name)
        if pk_valor is None:
            _log(f"ERROR: el archivo no tiene la partition key '{pk_name}'")
            return {"existe": False, "log": log}
        leido = tabla_ref.get_item(Key={pk_name: pk_valor}).get("Item")
        if leido:
            _log(f"Encontrado en {tabla} ({pk_name}='{pk_valor}') — ya está desplegado ahí")
            return {"existe": True, "tabla": tabla, "log": log}
        _log(f"No se encontró en {tabla} ({pk_name}='{pk_valor}')")
        return {"existe": False, "tabla": tabla, "log": log}
    except NoCredentialsError:
        _log("ERROR: no hay credenciales AWS configuradas")
    except EndpointConnectionError as e:
        _log(f"ERROR: no se pudo conectar a AWS (¿estás en la red del banco?): {e}")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        msg = e.response.get("Error", {}).get("Message", str(e))
        _log(f"ERROR de AWS ({code}): {msg}")
    except Exception as e:
        _log(f"ERROR verificando: {e}")
    return {"existe": False, "log": log}
