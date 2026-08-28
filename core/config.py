"""Configuración de la app: colores, íconos, estados y variables de entorno.

Solo constantes y lecturas de `.env` — sin lógica ni dependencias de Streamlit,
para que cualquier otro módulo pueda importar de acá sin arrastrar nada más.
"""
import os
import re
import base64

from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

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
