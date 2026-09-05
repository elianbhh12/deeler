"""Configuración de la app: colores, íconos, estados y variables de entorno.

Solo constantes y lecturas de `.env` — sin lógica ni dependencias de Streamlit,
para que cualquier otro módulo pueda importar de acá sin arrastrar nada más.
"""
import os
import re
import base64
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

#  Raíz del proyecto (core/ está un nivel adentro) — para resolver rutas
#  relativas en .env sin importar desde dónde se lance streamlit.
BASE_DIR = Path(__file__).resolve().parent.parent

#  Colores Banco (limpio y profesional)
ACCENT  = "#FDDA24"   # amarillo — acento primario
GREEN   = "#00C389"   # éxito, positivo
PURPLE  = "#9063CD"   # categoría / analítica
ORANGE  = "#FF7F41"   # advertencia, urgente
RED     = "#E53C3C"   # errores críticos
INK     = "#2C2A29"   # negro principal
MUTED   = "#78716C"   # texto secundario
WHITE   = "#FFFFFF"
SURFACE = "#FAFAF9"   # blanco roto

#  Íconos de estado — glifos monocromos, para HTML propio, tablas y Excel.
#  No dependen de una fuente de emoji: se ven igual en cualquier navegador/SO.
ICON_OK          = "✓"
ICON_ERROR       = "✗"
ICON_NA          = "–"
ICON_WARNING     = "⚠"
ICON_SUCCESS     = ICON_OK
ICON_FAIL        = ICON_ERROR

#  Íconos Material Symbols — para elementos nativos de Streamlit (icon=...):
#  st.error/warning/success/info/button/expander. Mismo estilo en toda la app,
#  sin emoji de colores.
MI_OK       = ":material/check_circle:"
MI_ERROR    = ":material/error:"
MI_WARNING  = ":material/warning:"
MI_NA       = ":material/remove_circle:"
MI_INFO     = ":material/info:"
MI_FOLDER   = ":material/folder_open:"
MI_FILE     = ":material/description:"
MI_DOWNLOAD = ":material/download:"
MI_UPLOAD   = ":material/cloud_upload:"
MI_REFRESH  = ":material/refresh:"
MI_SEARCH   = ":material/fact_check:"
MI_SETTINGS = ":material/settings:"
MI_HELP     = ":material/help:"
MI_APPROVE  = ":material/verified:"
MI_GUIDE    = ":material/menu_book:"
MI_CLOUD    = ":material/cloud_sync:"
MI_SUMMARY  = ":material/summarize:"

#  Estados de análisis (código lógico, separado del ícono de presentación)
ESTADO_LISTO         = "LISTO"
ESTADO_ERROR         = "ERROR"
ESTADO_INCOMPLETO    = "INCOMPLETO"
ESTADO_SIN_METADATA  = "SIN_METADATA"

ESTADO_ICON = {
    ESTADO_LISTO: ICON_OK,
    ESTADO_ERROR: ICON_ERROR,
    ESTADO_INCOMPLETO: ICON_WARNING,
    ESTADO_SIN_METADATA: ICON_WARNING,
}
ESTADO_TEXTO = {
    ESTADO_LISTO: "LISTO",
    ESTADO_ERROR: "ERRORES CRÍTICOS",
    ESTADO_INCOMPLETO: "INCOMPLETO",
    ESTADO_SIN_METADATA: "SIN METADATA",
}

#  Validaciones críticas: lista canónica usada tanto por analizar_hu (para calcular
#  estado_code) como por la UI (para el resumen del expander) — una sola fuente de verdad.
VALIDATION_KEYS = [
    "s3_path", "workflow_vs_id", "kafka", "coherencia", "out_zone_copiar",
    "ta_cu_name", "ta_type_prompts", "aid_tecnologia", "aid_type_topic",
    "ambiente_workflow_id", "udz_transmisiones", "last_step",
]

#  Configuración (variables de entorno)
ORG            = os.getenv("ADO_ORG")
PROJECT        = os.getenv("ADO_PROJECT")
TEAM           = os.getenv("ADO_TEAM")
AREA           = os.getenv("ADO_AREA")
PAT            = os.getenv("ADO_PAT")
ITERATION_PATH = os.getenv("ITERATION_PATH")
ROOT_FOLDER    = os.getenv("ROOT_FOLDER", r"C:\Backlog_Dealer")
DEALER_NAME    = os.getenv("DEALER_NAME", "Dealer")

KAFKA_TOPIC_REQUERIDO = "documentreceivingmanagement.documentuploadedv1"

# AID: valores válidos para TYPE en cada step de workflow_definition.
# "topic" es el caso normal (el step publica un evento). "write_results" es
# la excepción confirmada para un step final que solo escribe/guarda
# resultados y no publica evento — si aparece otro caso legítimo, agregarlo acá.
AID_TYPE_VALIDOS = {"topic", "write_results"}

#  Subida a AWS DynamoDB — ruta al JSON de credenciales temporales
#  (aws_access_key_id/secret/session_token/region_name) y nombres de tabla por
#  componente y ambiente. Coincide con lo que ya usa cargaaws.py en el banco.
#  Los nombres de tabla son editables por .env (por si cambian sin tocar código);
#  los valores de acá son el default si no se sobreescriben.
#
#  AWS_CRED_FILE no hace falta definirlo en .env: por default apunta a
#  "aws_credentials.json" en la raíz del proyecto (ya está en .gitignore).
#  Si se define, una ruta relativa se resuelve contra la raíz del proyecto
#  (no contra el directorio desde donde se lanzó streamlit) — así funciona
#  igual sin importar la máquina o desde dónde se corra run.bat.
_aws_cred_file_env = os.getenv("AWS_CRED_FILE", "").strip()
if _aws_cred_file_env:
    _aws_cred_path = Path(_aws_cred_file_env)
    AWS_CRED_FILE = str(_aws_cred_path if _aws_cred_path.is_absolute() else BASE_DIR / _aws_cred_path)
else:
    AWS_CRED_FILE = str(BASE_DIR / "aws_credentials.json")
AWS_AMBIENTES = ("qa", "pdn")
AWS_TABLAS = {
    "qa": {
        "aid": os.getenv("AWS_TABLA_AID_QA", "nu0087001-aid-r2-qa-dynamo-config-control"),
        "ta":  os.getenv("AWS_TABLA_TA_QA",  "nu0600001-plataforma-ia-qa-text-analyzer-table"),
        "udz": os.getenv("AWS_TABLA_UDZ_QA", "nu6490001-udz-qa-events-manager-table"),
    },
    "pdn": {
        "aid": os.getenv("AWS_TABLA_AID_PDN", "nu0087001-aid-r2-pdn-dynamo-config-control"),
        "ta":  os.getenv("AWS_TABLA_TA_PDN",  "nu0600001-plataforma-ia-pdn-text-analyzer-table"),
        "udz": os.getenv("AWS_TABLA_UDZ_PDN", "nu6490001-udz-pdn-events-manager-table"),
    },
}

# Sprint actual desde .env
_sprint_default_num = ""
if ITERATION_PATH:
    _m = re.search(r"Sprint\s*(\d+)", ITERATION_PATH, re.IGNORECASE)
    if _m:
        _sprint_default_num = int(_m.group(1))

# Sprints frecuentes — asegurar que el actual esté incluido y ordenado
_base_sprints = [251, 252, 253, 254, 255]
if _sprint_default_num and _sprint_default_num not in _base_sprints:
    _base_sprints.append(_sprint_default_num)
SPRINTS_FRECUENTES = sorted(_base_sprints)

AUTH    = base64.b64encode(f":{PAT}".encode()).decode() if PAT else ""
HEADERS = {"Authorization": f"Basic {AUTH}", "Content-Type": "application/json"}
