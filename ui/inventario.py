"""Pestaña "Extracción / Inventario": UI sobre python_pipeline/. No comparte
credenciales ni tablas con "Despliegues AID" (ver PIPELINE_CRED_FILE)."""
import html
import json
import re
from datetime import datetime
from pathlib import Path

import streamlit as st

from core.config import ICON_OK, ICON_ERROR, ICON_WARNING, MI_CLOUD, MI_SETTINGS, MI_OK, MI_ERROR, MI_INFO, MI_FOLDER, MI_CLEAN, PIPELINE_CRED_FILE
from core.utils import abrir_archivo

from python_pipeline import config as pconfig
from python_pipeline.aws_client import CredentialsError
from python_pipeline.download import TableNotFoundError
from python_pipeline.pipeline_service import ejecutar_pipeline_completo
from python_pipeline.limpieza import medir_descargas, limpiar_descargas_viejas

_LOG_SESSION_KEY = "inv_log_lineas"


def _render_panel_credenciales():
    """Mismo patrón que ui/aws_console.py, pero en PIPELINE_CRED_FILE."""
    _ruta = Path(PIPELINE_CRED_FILE)
    _existe = _ruta.exists()
    _estado_txt = (
        f"{ICON_OK} Configuradas — actualizadas {datetime.fromtimestamp(_ruta.stat().st_mtime).strftime('%d/%m/%Y %H:%M')}"
        if _existe else f"{ICON_WARNING} No configuradas todavía"
    )

    with st.expander(f"Credenciales AWS (Inventario) — {_estado_txt}", icon=MI_SETTINGS, expanded=not _existe):
        with st.form("form_credenciales_inventario", clear_on_submit=False):
            _access_key = st.text_input("Access Key ID", placeholder="AKIA... o ASIA...", key="inv_cred_access_key")
            _secret_key = st.text_input("Secret Access Key", type="password", key="inv_cred_secret_key")
            _session_token = st.text_input(
                "Session Token (solo si son credenciales temporales STS)",
                type="password", key="inv_cred_session_token",
                help="Dejalo vacío si es un usuario IAM con access key permanente.",
            )
            if st.form_submit_button("Guardar credenciales", icon=MI_OK, type="primary"):
                if not _access_key or not _secret_key:
                    st.error("Access Key ID y Secret Access Key son obligatorios.", icon=ICON_ERROR)
                else:
                    _creds = {
                        "aws_access_key_id": _access_key.strip(),
                        "aws_secret_access_key": _secret_key.strip(),
                    }
                    if _session_token.strip():
                        _creds["aws_session_token"] = _session_token.strip()
                    _ruta.write_text(json.dumps(_creds, indent=2, ensure_ascii=False), encoding="utf-8")
                    st.toast("Credenciales de Inventario guardadas", icon=MI_OK)
                    st.rerun()


def _render_panel_mantenimiento():
    """Limpieza manual de descargas/ viejas (ver python_pipeline/limpieza.py)."""
    resumen = medir_descargas()
    _titulo = f"Mantenimiento de disco — descargas/ ocupa {resumen.mb_totales} MB en {resumen.carpetas_de_fecha} carpetas"
    with st.expander(_titulo, icon=MI_CLEAN, expanded=False):
        if resumen.carpetas_de_fecha == 0:
            st.caption("Todavía no hay nada descargado.")
            return

        st.caption(
            "Los JSON crudos de cada corrida no se borran solos. Lo que importa de verdad ya está "
            "resumido en el maestro/historial acumulado — borrar descargas viejas no pierde esa información."
        )
        dias = st.number_input(
            "Conservar los últimos (días)", min_value=1, max_value=365, value=30, step=5, key="inv_limpieza_dias",
        )
        preview = limpiar_descargas_viejas(dias_retener=int(dias), dry_run=True)
        if not preview["borradas"]:
            st.caption(f"Nada para borrar — todo lo descargado tiene menos de {int(dias)} días.")
        else:
            st.warning(
                f"Se borrarían **{len(preview['borradas'])} carpetas** "
                f"(~{round(preview['bytes_liberados'] / (1024 * 1024), 1)} MB) con más de {int(dias)} días. "
                "Esto no afecta al maestro, historial ni matriz de ambientes acumulados.",
                icon=ICON_WARNING,
            )
            if st.button(f"Borrar {len(preview['borradas'])} carpetas viejas", key="inv_limpiar_confirmar", icon=MI_CLEAN):
                resultado = limpiar_descargas_viejas(dias_retener=int(dias), dry_run=False)
                st.toast(
                    f"{len(resultado['borradas'])} carpetas borradas "
                    f"({round(resultado['bytes_liberados'] / (1024 * 1024), 1)} MB liberados)",
                    icon=MI_OK,
                )
                st.rerun()


_PASO_RE = re.compile(r"^===\s*Paso (\d+)/(\d+):\s*(.+?)\s*===$")

# Mismo orden que los "Paso N/6" de pipeline_service.py.
_PASOS_LABELS = ["Descargar", "Comparar TA", "Subtipos", "Agrupar", "Maestro", "Excel"]


def _stepper_html(paso_actual: int, terminado: bool = False) -> str:
    """Reusa .pipeline-stepper/.pipeline-step de styles.py."""
    chips = []
    for i, label in enumerate(_PASOS_LABELS, start=1):
        if terminado or i < paso_actual:
            cls = "done"
        elif i == paso_actual:
            cls = "active"
        else:
            cls = ""
        chips.append(f'<div class="pipeline-step {cls}"><span class="pipeline-step-num">{i}</span>{html.escape(label)}</div>')
        if i < len(_PASOS_LABELS):
            chips.append('<span class="pipeline-arrow">→</span>')
    return f'<div class="pipeline-stepper">{"".join(chips)}</div>'


def _consola_html(log_lineas: list) -> str:
    """Consola oscura (clases .aws-console-* de Subir a AWS)."""
    if not log_lineas:
        return """
        <div class="aws-console-wrap">
            <div class="aws-console-bar">
                <span class="aws-console-dot red"></span><span class="aws-console-dot yellow"></span><span class="aws-console-dot green"></span>
                <span class="aws-console-bar-label">consola · pipeline de inventario</span>
            </div>
            <div class="aws-console"><span class="aws-console-empty">(sin actividad todavía — apretá "Ejecutar" arriba)</span></div>
        </div>
        """

    partes = []
    for linea in log_lineas:
        if not linea.strip():
            continue
        m = _PASO_RE.match(linea.strip())
        if m:
            _n, _total, _titulo = m.groups()
            partes.append(f'<div class="aws-console-line sep">Paso {_n}/{_total} — {html.escape(_titulo)}</div>')
            continue

        cuerpo = linea.strip()
        es_detalle = linea.startswith(" ")  # sub-línea con un dato, no el paso en sí
        if "no se pudo" in cuerpo.lower() or "omitido" in cuerpo.lower() or "omite" in cuerpo.lower():
            cls, icono = "warn", "⚠"
        elif es_detalle:
            cls, icono = "", "›"
        else:
            cls, icono = "ok", "✓"

        partes.append(f'<div class="aws-console-line {cls}"><span class="aws-console-icon">{icono}</span>{html.escape(cuerpo)}</div>')

    return f"""
    <div class="aws-console-wrap">
        <div class="aws-console-bar">
            <span class="aws-console-dot red"></span><span class="aws-console-dot yellow"></span><span class="aws-console-dot green"></span>
            <span class="aws-console-bar-label">consola · pipeline de inventario</span>
        </div>
        <div class="aws-console">{"".join(partes)}</div>
    </div>
    """


def _paso_actual_desde_log(log_lineas: list) -> int:
    """Último "Paso N/6" visto en el log."""
    actual = 0
    for linea in log_lineas:
        m = _PASO_RE.match(linea.strip())
        if m:
            actual = int(m.group(1))
    return actual


def _render_progreso(log_lineas: list, terminado: bool = False) -> str:
    paso_actual = _paso_actual_desde_log(log_lineas)
    return _stepper_html(paso_actual, terminado=terminado) + _consola_html(log_lineas)


def _stat(icon: str, clase: str, valor, label: str) -> str:
    return f"""
    <div class="inv-stat">
        <div class="inv-stat-icon {clase}">{icon}</div>
        <div>
            <div class="inv-stat-value">{valor}</div>
            <div class="inv-stat-label">{label}</div>
        </div>
    </div>
    """


def _render_resumen(resumen: dict, modo_descarga: str, ambiente: str):
    total_r3 = resumen.get("R3 analizados", "-")
    sin_match = resumen.get("R3 sin Text Analyzer (revisar)", 0) or 0
    repetidos = resumen.get("Subtipos de documento repetidos", 0) or 0
    con_match = resumen.get("Coincidencias R3 con Text Analyzer", "-")
    nuevos = resumen.get("Nuevos vs corrida anterior", "-")
    cambiaron = resumen.get("Cambiaron vs corrida anterior", "-")
    r2_total = resumen.get("Items en R2 (no procesados en el reporte agrupado)", "-")

    # Solo confiable en modo completo -- en incremental sería un "0" engañoso.
    eliminados_valor = resumen.get("Eliminados vs corrida anterior", "-")
    eliminados_txt = str(eliminados_valor) if modo_descarga == "completo" else "N/D"
    run_tag = resumen.get("Fecha de la corrida", "")

    stats_html = "".join([
        _stat("✓", "ok", con_match, "Con match en TA"),
        _stat("!", "warn" if sin_match else "ok", sin_match, "Sin match en TA"),
        _stat("≡", "warn" if repetidos else "ok", repetidos, "Subtipos repetidos"),
        _stat("+", "info", nuevos, "Nuevos"),
        _stat("~", "info", cambiaron, "Cambiaron"),
        _stat("−", "neutral", eliminados_txt, "Eliminados"),
        _stat("R2", "neutral", r2_total, "Items R2 (raw)"),
    ])

    st.markdown(f"""
    <div class="inv-panel">
        <div class="inv-panel-header">
            <div class="inv-panel-title">Resultado de la última corrida — {html.escape(ambiente.upper())}</div>
            <div class="inv-panel-meta">{html.escape(run_tag)}</div>
        </div>
        <div class="inv-hero">
            <div class="inv-hero-value">{total_r3}</div>
            <div class="inv-hero-label">flujos R3 analizados en esta corrida</div>
        </div>
        <div class="inv-stats-grid">{stats_html}</div>
    </div>
    """, unsafe_allow_html=True)

    st.caption(
        "Los R2 no pasan por la comparación con Text Analyzer, pero se acumulan igual que los R3 "
        '— quedan en su propia hoja "R2" en este reporte y en el maestro acumulado. '
        "\"Eliminados\" solo se calcula en modo completo."
    )

    with st.expander("Ver todos los datos de la corrida", icon=MI_INFO, expanded=False):
        st.table({"Dato": list(resumen.keys()), "Valor": [str(v) for v in resumen.values()]})


def render_inventario():
    st.markdown("""
    <div style="font-size:18px;font-weight:800;color:#2C2A29;margin-bottom:2px">Extracción / Inventario</div>
    <div style="font-size:12px;color:#78716C;margin-bottom:14px">
        Descarga e inventaría <b>config-control</b>, <b>text-analyzer</b> y <b>events-manager (UDZ)</b>
        desde DynamoDB, y arma los Excel de inventario por ambiente (reporte de la corrida, maestro
        acumulado, matriz qa/pdn/dev, historial de cambios). Un botón corre los 6 pasos del pipeline de una vez.
        Herramienta independiente de "Despliegues AID": no comparte credenciales ni tablas.
    </div>
    """, unsafe_allow_html=True)

    _render_panel_credenciales()
    _render_panel_mantenimiento()

    if not Path(PIPELINE_CRED_FILE).exists():
        st.info("Configurá las credenciales AWS de Inventario arriba antes de ejecutar el pipeline.", icon=MI_INFO)
        return

    st.markdown('<div class="step-card-label">Parámetros de la corrida</div>', unsafe_allow_html=True)
    with st.container(key="inv_parametros", border=True):
        col1, col2 = st.columns(2)
        with col1:
            ambiente = st.radio(
                "Ambiente", options=list(pconfig.ENVIRONMENTS), format_func=lambda a: a.upper(),
                horizontal=True, key="inv_ambiente",
            )
        with col2:
            modo_descarga = st.radio(
                "Modo de descarga", options=["incremental", "completo"],
                format_func=lambda m: "Incremental (rápido)" if m == "incremental" else "Completo (detecta eliminados)",
                horizontal=True, key="inv_modo_descarga",
                help="'Incremental' (default, rápido): solo trae lo nuevo desde la última descarga. "
                     "'Completo' (más lento): trae todo — necesario de vez en cuando para detectar eliminados reales.",
            )

        _clic_ejecutar = st.button(
            f"Ejecutar pipeline completo en {ambiente.upper()}", key="inv_ejecutar", type="primary",
            icon=MI_CLOUD, width='stretch',
        )

    if _clic_ejecutar:
        st.session_state[_LOG_SESSION_KEY] = []

        # st.status: el título se actualiza en vivo con el paso actual.
        with st.status(f"Iniciando pipeline en {ambiente.upper()}...", expanded=True) as status:
            _log_placeholder = st.empty()
            _log_placeholder.markdown(_render_progreso([]), unsafe_allow_html=True)

            def _log(mensaje: str) -> None:
                for _linea in mensaje.splitlines():
                    st.session_state[_LOG_SESSION_KEY].append(_linea)
                lineas = st.session_state[_LOG_SESSION_KEY]
                _log_placeholder.markdown(_render_progreso(lineas), unsafe_allow_html=True)
                _paso = _paso_actual_desde_log(lineas)
                if _paso:
                    status.update(label=f"Paso {_paso}/{len(_PASOS_LABELS)} — {_PASOS_LABELS[_paso - 1]}...")

            try:
                resultado = ejecutar_pipeline_completo(
                    environment=ambiente, modo_descarga=modo_descarga,
                    credenciales_file=Path(PIPELINE_CRED_FILE), log=_log,
                )
            except (CredentialsError, TableNotFoundError) as exc:
                status.update(label="Error de credenciales o tabla", state="error")
                st.error(str(exc), icon=MI_ERROR)
                return
            except Exception as exc:
                status.update(label="Error inesperado", state="error")
                st.error(f"Error inesperado corriendo el pipeline: {exc}", icon=MI_ERROR)
                return

            _log_placeholder.markdown(_render_progreso(st.session_state[_LOG_SESSION_KEY], terminado=bool(resultado.resumen)), unsafe_allow_html=True)
            status.update(
                label=f"Pipeline completo en {ambiente.upper()}" if resultado.resumen else f"Terminó sin generar Excel en {ambiente.upper()}",
                state="complete",
            )

        st.session_state["inv_ultimo_resultado"] = resultado
    else:
        _terminado = bool(st.session_state.get("inv_ultimo_resultado") and st.session_state["inv_ultimo_resultado"].resumen)
        st.markdown(_render_progreso(st.session_state.get(_LOG_SESSION_KEY, []), terminado=_terminado), unsafe_allow_html=True)

    resultado = st.session_state.get("inv_ultimo_resultado")
    if not resultado:
        return
    if resultado.environment != ambiente:
        st.info(
            f"Todavía no corriste el pipeline para **{ambiente.upper()}** en esta sesión — el resultado que "
            f"tenés guardado es de **{resultado.environment.upper()}** (sigue disponible si volvés a ese ambiente). "
            f"Apretá \"Ejecutar pipeline completo en {ambiente.upper()}\" arriba para verlo acá.",
            icon=MI_INFO,
        )
        return

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    if resultado.resumen:
        _render_resumen(resultado.resumen, resultado.modo_descarga, resultado.environment)
    else:
        st.info(
            "El pipeline no llegó a generar el Excel — revisá el log de arriba "
            "(probablemente no había datos R3 o Text Analyzer en esta descarga).",
            icon=MI_INFO,
        )

    _archivos = [
        ("Reporte de esta corrida", "Foto de esta corrida puntual", resultado.excel_path),
        ("Maestro acumulado", "Todo lo conocido del ambiente, R2 incluido", resultado.maestro_path),
        ("Matriz de ambientes", "Presencia en qa / pdn / dev", resultado.matriz_path),
        ("Historial de cambios", "Log de nuevo / cambio / eliminado", resultado.historial_path),
    ]
    _disponibles = [(etq, sub, p) for etq, sub, p in _archivos if p]
    if _disponibles:
        st.markdown('<div class="inv-files-title">Excel generados</div>', unsafe_allow_html=True)
        cols = st.columns(len(_disponibles))
        for col, (etiqueta, subtitulo, ruta) in zip(cols, _disponibles):
            with col:
                with st.container(border=True):
                    st.markdown(f"**{etiqueta}**")
                    st.caption(subtitulo)
                    if st.button("Abrir", key=f"inv_abrir_{etiqueta}", width='stretch', icon=MI_FOLDER):
                        abrir_archivo(Path(ruta))
