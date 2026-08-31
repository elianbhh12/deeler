"""Consola de subida a AWS DynamoDB — sección aparte del detalle de la HU
(no anidada dentro de la tarjeta de validación) para que el resultado de cada
intento, éxito o error, quede siempre visible en un log tipo terminal, igual
que los print() que ya conocen del script `cargaaws.py`.

Sube exactamente el TA/AID/UDZ que la HU activa (la seleccionada en "Análisis
Técnico Detallado", arriba) tiene resuelto — no escanea una carpeta. Siempre
intenta el envío real (sin modo simulación): si falla la conexión o las
credenciales, el error real de AWS queda en el log.
"""
import html
import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from core.config import ICON_OK, ICON_ERROR, ICON_WARNING, ICON_NA, MI_CLOUD, MI_INFO, MI_REFRESH, MI_SETTINGS, MI_OK, AWS_TABLAS, AWS_CRED_FILE
from core.analysis import _val_ok, analizar_hu
from core.aws_upload import subir_componente
from core.utils import obtener_usuario_actual

#  Qué validaciones (de las 12 críticas) son el criterio de aceptación de cada
#  componente para poder subirlo — no es un gate duro (el archivo se puede
#  subir igual), es la señal que se muestra para decidir con confianza.
CRITERIOS_ACEPTACION = {
    "ta": (
        ["kafka", "ta_cu_name", "ta_type_prompts", "coherencia"],
        "kafka_output_topic correcto · cu_name presente · type='prompts' · "
        "cu_name coincide con AID.use_case",
    ),
    "aid": (
        ["aid_tecnologia", "aid_type_topic", "out_zone_copiar", "last_step",
         "s3_path", "workflow_vs_id", "ambiente_workflow_id", "coherencia"],
        "tecnologia='AID' · TYPE válido por step · out_zone/copiarResultadoBucket "
        "coherentes · LAST_STEP en False · s3_path y workflow_name coherentes con UDZ",
    ),
    "udz": (
        ["udz_transmisiones", "s3_path", "workflow_vs_id", "ambiente_workflow_id"],
        "reglas de crudos/resultados cumplidas · s3_path e id coherentes con AID",
    ),
}

#  Archivos AID reales pueden tener decenas de steps (workflow_definition muy
#  anidado) — renderizar eso entero con st.json() por default puede colgar el
#  navegador. Arriba de este tamaño, se muestra una vista previa en texto
#  truncada y el JSON completo queda a un click, no automático.
LIMITE_PREVIEW_KB = 30


def _motivos_bloqueo(val: dict, keys: list) -> list:
    """Validaciones relevantes para este componente que están en error (no N/A)."""
    return [k for k in keys if not val.get(k, {}).get("na", False) and not _val_ok(val.get(k, {}))]


def _verificar_ambiente(tipo: str, val: dict, ambiente_destino: str):
    """Antes de subir, confirma que el archivo realmente es del ambiente
    elegido — evita mandar por error un AID/UDZ de QA a la tabla de PDN (o
    viceversa). TA no declara ambiente en su estructura, no aplica.

    AID: se fija en el ambiente que ya detectó analizar_hu a partir del
    s3_path (debe contener "-qa-"/"-pdn-"/etc.).
    UDZ: mismo criterio pero sobre el campo `id` del UDZ.

    Si el ambiente no se pudo detectar (DESCONOCIDO), bloquea igual — no
    hay forma de confirmar que coincide con QA/PDN, así que no se sube."""
    if tipo == "ta":
        return True, None

    if tipo == "aid":
        detectado = val.get("ambiente", {}).get("ambiente")
    else:  # udz
        detectado = val.get("ambiente_workflow_id", {}).get("udz_ambiente")

    if not detectado or detectado == "DESCONOCIDO":
        return False, f"No se pudo detectar el ambiente del {tipo.upper()} — revisá que el s3_path/id contenga '{ambiente_destino}'"
    if detectado.upper() != ambiente_destino.upper():
        return False, f"El {tipo.upper()} parece ser de {detectado}, no de {ambiente_destino.upper()} — no se sube"
    return True, None


def _render_consola(log_lineas):
    if not log_lineas:
        st.markdown('<div class="aws-console"><span class="aws-console-empty">(sin actividad todavía)</span></div>', unsafe_allow_html=True)
        return

    partes = []
    for linea in log_lineas:
        if not linea:
            partes.append('<div style="height:8px"></div>')
            continue
        cls = "err" if "ERROR" in linea else ("warn" if "AVISO" in linea else ("ok" if ("OK" in linea or "Verificado" in linea) else ""))
        partes.append(f'<div class="aws-console-line {cls}">{html.escape(linea)}</div>')

    st.markdown(f'<div class="aws-console">{"".join(partes)}</div>', unsafe_allow_html=True)


def _render_contenido(archivo: Path, tipo: str):
    tam_kb = archivo.stat().st_size / 1024
    try:
        texto = archivo.read_text(encoding="utf-8")
    except Exception as e:
        st.caption(f"No se pudo leer el archivo: {e}")
        return

    if tam_kb <= LIMITE_PREVIEW_KB:
        with st.expander("Ver contenido a subir", expanded=False):
            try:
                st.json(json.loads(texto))
            except Exception as e:
                st.caption(f"JSON inválido: {e}")
        return

    with st.expander(f"Ver contenido a subir — archivo grande ({tam_kb:.0f} KB)", expanded=False):
        st.caption("Vista previa truncada para no colgar el navegador. Cargá el JSON completo solo si lo necesitás.")
        st.code(texto[:2000] + ("\n…(truncado)" if len(texto) > 2000 else ""), language="json")
        key_full = f"aws_full_{tipo}"
        if st.session_state.get(key_full):
            try:
                st.json(json.loads(texto))
            except Exception as e:
                st.caption(f"JSON inválido: {e}")
        elif st.button("Cargar JSON completo", key=f"aws_cargar_full_{tipo}"):
            st.session_state[key_full] = True
            st.rerun()


def _persistir_subida_aws(r: dict, tipo: str, ambiente: str, tabla: str, resultados: list):
    """Registra quién subió este componente, cuándo, a qué ambiente y tabla —
    misma idea que la trazabilidad de QA/aprobación: es un acto explícito del
    usuario, así que se guarda en analisis_tecnico.json (no solo en el log de
    sesión, que se pierde al recargar la página) para que quede en el Excel."""
    hu_folder_str = r.get("hu_folder")
    if not hu_folder_str:
        return

    r[f"{tipo}_aws_ambiente"] = ambiente
    r[f"{tipo}_aws_por"] = obtener_usuario_actual()
    r[f"{tipo}_aws_en"] = datetime.now().isoformat()
    r[f"{tipo}_aws_tabla"] = tabla

    out_path = Path(hu_folder_str) / "analisis" / "analisis_tecnico.json"
    out_path.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")

    for i, x in enumerate(resultados):
        if str(x.get("hu_id")) == str(r.get("hu_id")):
            resultados[i] = r
            break
    st.session_state["resultados"] = resultados


def _render_panel_credenciales():
    """Formulario para cargar/actualizar aws_credentials.json sin salir de la
    app ni editar el archivo a mano. Nunca se muestran los valores ya
    guardados (son secretos) — solo si hay o no credenciales configuradas."""
    _ruta = Path(AWS_CRED_FILE)
    _existe = _ruta.exists()
    _estado_txt = f"{ICON_OK} Configuradas — actualizadas {datetime.fromtimestamp(_ruta.stat().st_mtime).strftime('%d/%m/%Y %H:%M')}" if _existe else f"{ICON_WARNING} No configuradas todavía"

    with st.expander(f"Credenciales AWS — {_estado_txt}", icon=MI_SETTINGS, expanded=not _existe):
        st.caption(
            f"Se guardan en `{_ruta.name}` en la raíz del proyecto (nunca se sube a git). "
            f"Nunca se muestran acá los valores ya guardados, solo si hay algo cargado."
        )
        with st.form("form_credenciales_aws", clear_on_submit=False):
            _access_key = st.text_input("Access Key ID", placeholder="AKIA... o ASIA...")
            _secret_key = st.text_input("Secret Access Key", type="password")
            _session_token = st.text_input(
                "Session Token (solo si son credenciales temporales STS)",
                type="password",
                help="Dejalo vacío si es un usuario IAM con access key permanente (ej. cuenta personal).",
            )
            _region = st.text_input("Región", value="us-east-1")

            if st.form_submit_button("Guardar credenciales", icon=MI_OK, type="primary"):
                if not _access_key or not _secret_key or not _region:
                    st.error("Access Key ID, Secret Access Key y Región son obligatorios.", icon=ICON_ERROR)
                else:
                    _creds = {
                        "aws_access_key_id": _access_key.strip(),
                        "aws_secret_access_key": _secret_key.strip(),
                        "region_name": _region.strip(),
                    }
                    if _session_token.strip():
                        _creds["aws_session_token"] = _session_token.strip()
                    _ruta.write_text(json.dumps(_creds, indent=2, ensure_ascii=False), encoding="utf-8")
                    st.toast("Credenciales AWS guardadas", icon=MI_OK)
                    st.rerun()


def render_aws_console(resultados):
    st.divider()
    st.markdown("""
    <div style="font-size:18px;font-weight:800;color:#2C2A29;margin-bottom:2px">Subir a AWS</div>
    <div style="font-size:12px;color:#78716C;margin-bottom:14px">
        Consola separada del detalle de la HU — así el resultado de cada intento (éxito o error) queda siempre a la vista.
        El envío es siempre real: si falla la conexión o las credenciales, el log muestra el error tal cual lo da AWS.
    </div>
    """, unsafe_allow_html=True)

    _render_panel_credenciales()

    hu_id_activa = st.session_state.get("hu_activa_id")
    r = next((x for x in resultados if str(x.get("hu_id")) == str(hu_id_activa)), None)
    if not r:
        st.info("Seleccioná una HU en 'Análisis Técnico Detallado' arriba para habilitar la subida.", icon=MI_INFO)
        return

    val = r.get("validaciones", {})
    st.caption(f"HU activa: {r.get('hu_id')} — {r.get('hu_title', '')}")

    col_amb, col_pdn = st.columns([0.3, 0.7], vertical_alignment="center")
    with col_amb:
        ambiente = st.radio(
            "Ambiente destino", ["qa", "pdn"], format_func=lambda a: a.upper(),
            horizontal=True, key="aws_ambiente",
        )
    confirma_pdn = True
    with col_pdn:
        if ambiente == "pdn":
            confirma_pdn = st.checkbox(
                f"{ICON_WARNING} Confirmo que quiero escribir en PRODUCCIÓN (PDN) — esto no es reversible",
                value=False, key="aws_confirma_pdn",
            )

    archivos_activos = {"ta": r.get("ta_activo"), "aid": r.get("aid_activo"), "udz": r.get("udz_activo")}
    cols = st.columns(3, gap="medium")

    for (tipo, (keys, criterio_txt)), col in zip(CRITERIOS_ACEPTACION.items(), cols):
        with col:
            archivo = archivos_activos.get(tipo)
            # El path activo viene de analisis_tecnico.json y puede quedar
            # obsoleto: si el archivo real se borró/movió (o falló al
            # descomprimirse) desde el último análisis, no debe romper la
            # consola — se trata como "no disponible" hasta que se actualice.
            archivo_perdido = bool(archivo) and not Path(archivo).exists()
            if archivo_perdido:
                archivo = None

            tabla_destino = AWS_TABLAS.get(ambiente, {}).get(tipo, "(sin configurar)")
            motivos = _motivos_bloqueo(val, keys) if archivo else []
            listo = bool(archivo) and not motivos
            icono = ICON_OK if listo else (ICON_WARNING if archivo else ICON_NA)
            cls_card = "ok" if listo else ("warn" if archivo else "na")

            ultima_subida = ""
            if r.get(f"{tipo}_aws_por"):
                _fecha = (r.get(f"{tipo}_aws_en") or "")[:16].replace("T", " ")
                _amb_prev = (r.get(f"{tipo}_aws_ambiente") or "").upper()
                ultima_subida = (
                    f"<div style='font-size:10.5px;color:#78716C;margin-top:6px'>"
                    f"{ICON_OK} Último envío: {html.escape(r[f'{tipo}_aws_por'])} · {_amb_prev} · {_fecha}</div>"
                )

            col_titulo, col_refresh = st.columns([0.82, 0.18], vertical_alignment="center")
            with col_titulo:
                st.markdown(f'<div class="aws-card-title" style="margin-top:6px">{icono} {tipo.upper()}</div>', unsafe_allow_html=True)
            with col_refresh:
                if st.button(
                    "", key=f"aws_console_refresh_{tipo}", icon=MI_REFRESH,
                    help=f"Relee el {tipo.upper()} del disco y recalcula sus validaciones",
                ):
                    hu_folder_str = r.get("hu_folder")
                    if hu_folder_str:
                        nuevo = analizar_hu(Path(hu_folder_str))
                        for i, x in enumerate(resultados):
                            if str(x.get("hu_id")) == str(r.get("hu_id")):
                                resultados[i] = nuevo
                                break
                        st.session_state["resultados"] = resultados
                        st.rerun()

            st.markdown(f"""
            <div class="aws-card {cls_card}" style="border-top-left-radius:0;border-top-right-radius:0;margin-top:-8px">
                <div class="aws-card-criterio">{criterio_txt}</div>
                <div class="aws-table-tag"><b>Tabla:</b> {tabla_destino}</div>
                {ultima_subida}
            </div>
            """, unsafe_allow_html=True)

            if motivos:
                alerta_items = "".join(
                    f"<div style='margin-top:3px'>• <code>{html.escape(m)}</code>: {html.escape(val.get(m, {}).get('detalle', ''))}</div>"
                    for m in motivos
                )
                st.markdown(f"""
                <div class="aws-alert">
                    <b>{ICON_WARNING} No está listo para subir ({len(motivos)}):</b>
                    {alerta_items}
                </div>
                """, unsafe_allow_html=True)

            amb_ok, amb_motivo = _verificar_ambiente(tipo, val, ambiente) if archivo else (True, None)
            if amb_motivo:
                st.markdown(f"""
                <div class="aws-alert" style="background:#FEE2E2;border-color:#FCA5A5;color:#991B1B">
                    <b>{ICON_ERROR} Ambiente no coincide:</b> {html.escape(amb_motivo)}
                </div>
                """, unsafe_allow_html=True)

            if archivo_perdido:
                st.markdown(f"""
                <div class="aws-alert" style="background:#FEE2E2;border-color:#FCA5A5;color:#991B1B">
                    <b>{ICON_ERROR} El archivo ya no está en disco</b> — puede haberse movido, borrado, o
                    falló al descomprimirse. Apretá el ícono de actualizar (arriba) para resincronizar.
                </div>
                """, unsafe_allow_html=True)

            if not archivo:
                ayuda = f"No hay archivo {tipo.upper()} activo para esta HU"
            elif not amb_ok:
                ayuda = amb_motivo
            elif ambiente == "pdn" and not confirma_pdn:
                ayuda = "Marcá la confirmación de PDN primero"
            else:
                ayuda = None

            if archivo:
                _render_contenido(Path(archivo), tipo)

            if st.button(
                f"Subir {tipo.upper()}", key=f"aws_console_subir_{tipo}", width='stretch',
                icon=MI_CLOUD, disabled=bool(ayuda), help=ayuda,
            ):
                resultado = subir_componente(tipo, Path(archivo), ambiente=ambiente)
                log_acumulado = st.session_state.setdefault("aws_console_log", [])
                log_acumulado.extend(resultado.get("log", []))
                log_acumulado.append("")

                if resultado.get("ok"):
                    _persistir_subida_aws(r, tipo, ambiente, resultado.get("tabla"), resultados)

                st.rerun()

    st.markdown("<div style='font-size:12px;font-weight:700;color:#78716C;margin-top:16px;margin-bottom:6px'>CONSOLA</div>", unsafe_allow_html=True)
    _render_consola(st.session_state.get("aws_console_log", []))
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    if st.button("Limpiar consola", key="aws_console_limpiar"):
        st.session_state["aws_console_log"] = []
        st.rerun()
