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
import re
from datetime import datetime
from pathlib import Path

import streamlit as st

from core.config import ICON_OK, ICON_ERROR, ICON_WARNING, ICON_NA, MI_CLOUD, MI_INFO, MI_REFRESH, MI_SETTINGS, MI_OK, MI_ERROR, AWS_TABLAS, AWS_CRED_FILE
from core.analysis import _val_ok, analizar_hu, detectar_slots_udz
from core.aws_upload import subir_componente
from core.utils import obtener_usuario_actual

#  Nombres para mostrar según el tipo de UDZ detectado (ver
#  core.analysis.detectar_slots_udz) — CRUDOS = entrada, RESULTADOS = salida
#  (transmisión). Se usan tanto para el título largo de la tarjeta como para
#  el texto corto del botón.
_UDZ_NOMBRE_LARGO = {"CRUDOS": "Crudos (entrada)", "RESULTADOS": "Transmisión (salida)"}
_UDZ_NOMBRE_CORTO = {"CRUDOS": "UDZ Crudos", "RESULTADOS": "UDZ Result."}

#  Tope de líneas que se guardan del log de consola — sin esto crece sin
#  límite durante una sesión larga con muchas subidas y se vuelve pesado de
#  renderizar. Se recorta a las más recientes, que son las que importan.
LIMITE_LOG_LINEAS = 300

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


#  Cada línea del log llega como "[HH:MM:SS] mensaje" (ver core/aws_upload._log)
#  — se separa la hora del mensaje para poder atenuarla visualmente y dejar
#  el mensaje como protagonista, en vez de una sola tira de texto plana.
_TS_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$")


def _render_consola(log_lineas):
    if not log_lineas:
        st.markdown("""
        <div class="aws-console-wrap">
            <div class="aws-console-bar">
                <span class="aws-console-dot red"></span><span class="aws-console-dot yellow"></span><span class="aws-console-dot green"></span>
                <span class="aws-console-bar-label">consola · subida a AWS</span>
            </div>
            <div class="aws-console"><span class="aws-console-empty">(sin actividad todavía)</span></div>
        </div>
        """, unsafe_allow_html=True)
        return

    partes = []
    for linea in log_lineas:
        if not linea:
            partes.append('<div style="height:10px"></div>')
            continue

        if linea.startswith("──"):
            titulo = linea.strip("─ ")
            partes.append(f'<div class="aws-console-line sep">{html.escape(titulo)}</div>')
            continue

        m = _TS_RE.match(linea)
        ts, cuerpo = (m.group(1), m.group(2)) if m else (None, linea)

        if "ERROR" in cuerpo:
            cls, icono = "err", "✗"
        elif "AVISO" in cuerpo:
            cls, icono = "warn", "⚠"
        elif cuerpo.startswith("put_item OK") or "Verificado" in cuerpo:
            cls, icono = "ok", "✓"
        else:
            cls, icono = "", "›"

        _ts_html = f'<span class="aws-console-ts">{ts}</span>' if ts else ""
        partes.append(
            f'<div class="aws-console-line {cls}">{_ts_html}'
            f'<span class="aws-console-icon">{icono}</span>{html.escape(cuerpo)}</div>'
        )

    st.markdown(f"""
    <div class="aws-console-wrap">
        <div class="aws-console-bar">
            <span class="aws-console-dot red"></span><span class="aws-console-dot yellow"></span><span class="aws-console-dot green"></span>
            <span class="aws-console-bar-label">consola · subida a AWS</span>
        </div>
        <div class="aws-console">{"".join(partes)}</div>
    </div>
    """, unsafe_allow_html=True)


def _agregar_al_log(label: str, ambiente: str, resultado: dict):
    """Agrega el log de un intento de subida a la consola acumulada, con un
    separador con hora para poder distinguir un intento del siguiente en una
    sesión larga, y recorta el total para que no crezca sin límite."""
    log_acumulado = st.session_state.setdefault("aws_console_log", [])
    _hora = datetime.now().strftime("%H:%M:%S")
    log_acumulado.append(f"── {label.upper()} → {ambiente.upper()} · {_hora} ──")
    log_acumulado.extend(resultado.get("log", []))
    log_acumulado.append("")
    if len(log_acumulado) > LIMITE_LOG_LINEAS:
        log_acumulado[:] = log_acumulado[-LIMITE_LOG_LINEAS:]
    st.session_state["_aws_ultimo_resultado"] = {
        "label": label, "ambiente": ambiente, "ok": bool(resultado.get("ok")), "en": _hora,
    }


def _construir_componentes(r: dict) -> list:
    """Arma la lista de componentes a mostrar en la consola de subida: TA y
    AID siempre son uno solo, UDZ puede ser uno o dos (ver
    detectar_slots_udz) — cada elemento trae "clave" (prefijo de los campos
    de trazabilidad `{clave}_aws_por/en/ambiente/tabla`, y las claves de
    widgets), "tipo_tabla" (ta/aid/udz — para AWS_TABLAS y subir_componente,
    que no conocen la separación crudos/resultados, van a la misma tabla) y
    "label" (texto para mostrar)."""
    componentes = [
        {"clave": "ta", "tipo_tabla": "ta", "label": "TA", "label_corto": "TA",
         "archivo": r.get("ta_activo"), "es_activo": True},
        {"clave": "aid", "tipo_tabla": "aid", "label": "AID", "label_corto": "AID",
         "archivo": r.get("aid_activo"), "es_activo": True},
    ]

    slots_udz = detectar_slots_udz(r)
    if len(slots_udz) == 1:
        s = slots_udz[0]
        _sub = f" ({s['tipo']})" if s["tipo"] else ""
        componentes.append({
            "clave": "udz", "tipo_tabla": "udz", "label": f"UDZ{_sub}", "label_corto": "UDZ",
            "archivo": s["archivo"], "es_activo": True,
        })
    else:
        for s in slots_udz:
            componentes.append({
                "clave": f"udz_{s['tipo'].lower()}", "tipo_tabla": "udz",
                "label": f"UDZ — {_UDZ_NOMBRE_LARGO.get(s['tipo'], s['tipo'])}",
                "label_corto": _UDZ_NOMBRE_CORTO.get(s["tipo"], "UDZ"),
                "archivo": s["archivo"], "es_activo": s["es_activo"],
            })
    return componentes


def _estado_componente(tipo_tabla: str, label: str, keys: list, archivo, val: dict,
                        ambiente: str, confirma_pdn: bool, es_activo: bool = True):
    """Calcula, para un componente, si está listo para subir y por qué no si
    no lo está — un solo lugar de verdad que usan el resumen de arriba, la
    tarjeta individual y el botón de subida masiva, así nunca se
    desincronizan entre sí."""
    archivo_perdido = bool(archivo) and not Path(archivo).exists()
    if archivo_perdido:
        archivo = None

    # "val" son las 12 validaciones críticas, calculadas sobre un solo UDZ a
    # la vez (el activo) — si este componente NO es el activo, esos
    # resultados describen al OTRO archivo, no al suyo. Mostrarlos igual acá
    # sería engañoso (parecería que este archivo específico tiene esos
    # errores), así que se omiten: la única razón de bloqueo relevante es
    # "todavía no se validó".
    if archivo and es_activo:
        motivos = _motivos_bloqueo(val, keys)
        amb_ok, amb_motivo = _verificar_ambiente(tipo_tabla, val, ambiente)
    else:
        motivos = []
        amb_ok, amb_motivo = True, None
    listo = bool(archivo) and not motivos and es_activo

    if not archivo:
        ayuda = f"No hay archivo {label} para esta HU"
    elif not es_activo:
        # Las 12 validaciones críticas corren sobre un solo UDZ a la vez (el
        # "activo" elegido arriba en "UDZ a usar") — este es el otro archivo
        # UDZ de la HU, que todavía no se validó, así que no se deja subir
        # ciego: primero hay que elegirlo como activo para validarlo.
        ayuda = "Este es el otro archivo UDZ de la HU — elegilo en 'UDZ a usar' (arriba) para validarlo antes de subirlo"
    elif not amb_ok:
        ayuda = amb_motivo
    elif ambiente == "pdn" and not confirma_pdn:
        ayuda = "Marcá la confirmación de PDN primero"
    else:
        ayuda = None

    return {
        "archivo": archivo, "archivo_perdido": archivo_perdido,
        "motivos": motivos, "listo": listo,
        "amb_ok": amb_ok, "amb_motivo": amb_motivo,
        "ayuda": ayuda, "puede_subir": ayuda is None,
    }


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

    # Las keys de "Ambiente destino" y la confirmación de PDN se escopan por
    # HU (no son globales): antes eran una sola key compartida entre todas
    # las HU, así que si dejabas "PDN" seleccionado (o la confirmación
    # marcada) en una HU y cambiabas a otra en "Selecciona una HU", esa
    # elección quedaba pegada — ibas a ver la alerta de "el AID parece ser
    # de QA, no de PDN" sin haber tocado el radio vos mismo, porque en
    # realidad seguía en el valor de la HU anterior. Al escoparlo por HU,
    # cada HU arranca en QA sin confirmar, sin arrastrar nada de la anterior.
    #
    # La zona entera vive en un container con key fija ("aws_zona_ambiente")
    # para poder pintarle un fondo/borde de alerta cuando el modo es PDN —
    # antes el selector era un radio suelto, tan discreto como cualquier
    # otro campo, sin nada que refuerce visualmente "estás por escribir en
    # producción" más allá de leer la palabra en el radio.
    with st.container(key="aws_zona_ambiente", border=True):
        col_amb, col_pdn = st.columns([0.3, 0.7], vertical_alignment="center")
        with col_amb:
            ambiente = st.radio(
                "Ambiente destino", ["qa", "pdn"], format_func=lambda a: a.upper(),
                horizontal=True, key=f"aws_ambiente_{hu_id_activa}",
            )
        confirma_pdn = True
        with col_pdn:
            if ambiente == "pdn":
                confirma_pdn = st.checkbox(
                    f"{ICON_WARNING} Confirmo que quiero escribir en PRODUCCIÓN (PDN) — esto no es reversible",
                    value=False, key=f"aws_confirma_pdn_{hu_id_activa}",
                )
            else:
                st.caption("Los componentes se suben a las tablas de QA — ambiente de pruebas.")

    _modo_pdn = ambiente == "pdn"
    st.markdown(f"""
    <style>
    div.st-key-aws_zona_ambiente {{
        background: {"#FEF2F2" if _modo_pdn else "var(--track)"} !important;
        border: 1.5px solid {"var(--red)" if _modo_pdn else "var(--line)"} !important;
        border-radius: 12px !important;
    }}
    </style>
    """, unsafe_allow_html=True)
    # Componentes a subir — TA y AID son siempre uno, UDZ puede ser uno o dos
    # (crudos/resultados como archivos separados, ver detectar_slots_udz).
    componentes = _construir_componentes(r)

    # Un solo cálculo de estado por componente, reusado por el resumen de
    # arriba, el botón masivo y cada tarjeta — así nunca se desincronizan.
    estados = {}
    for comp in componentes:
        keys, _criterio = CRITERIOS_ACEPTACION[comp["tipo_tabla"]]
        estados[comp["clave"]] = _estado_componente(
            comp["tipo_tabla"], comp["label"], keys, comp["archivo"], val,
            ambiente, confirma_pdn, comp["es_activo"],
        )
    _n_listos = sum(1 for e in estados.values() if e["puede_subir"])
    _n_total = len(componentes)
    _todos_listos = _n_listos == _n_total

    st.markdown(f"""
    <div class="aws-summary-strip">
        <div class="aws-summary-text">{ICON_OK if _todos_listos else ICON_WARNING} {_n_listos} de {_n_total} listos para subir a {ambiente.upper()}</div>
    </div>
    """, unsafe_allow_html=True)

    with st.container(key="aws_subir_todos_wrap"):
        if st.button(
            f"Subir los {_n_total} componentes", key="aws_console_subir_todos", width='stretch',
            icon=MI_CLOUD, type="primary", disabled=not _todos_listos,
            help=None if _todos_listos else "Todos los componentes deben estar listos (sin alertas) para usar esta opción",
        ):
            for comp in componentes:
                archivo = estados[comp["clave"]]["archivo"]
                with st.spinner(f"Subiendo {comp['label']} a {ambiente.upper()}..."):
                    resultado = subir_componente(comp["tipo_tabla"], Path(archivo), ambiente=ambiente)
                _agregar_al_log(comp["label"], ambiente, resultado)
                if resultado.get("ok"):
                    _persistir_subida_aws(r, comp["clave"], ambiente, resultado.get("tabla"), resultados)
            st.rerun()

    cols = st.columns(_n_total, gap="medium")

    for comp, col in zip(componentes, cols):
        with col:
            clave = comp["clave"]
            label = comp["label"]
            _, criterio_txt = CRITERIOS_ACEPTACION[comp["tipo_tabla"]]
            estado = estados[clave]
            archivo = estado["archivo"]
            tabla_destino = AWS_TABLAS.get(ambiente, {}).get(comp["tipo_tabla"], "(sin configurar)")
            listo = estado["listo"]
            icono = ICON_OK if listo else (ICON_WARNING if archivo else ICON_NA)
            cls_card = "ok" if listo else ("warn" if archivo else "na")

            ultima_subida = ""
            if r.get(f"{clave}_aws_por"):
                _fecha = (r.get(f"{clave}_aws_en") or "")[:16].replace("T", " ")
                _amb_prev = (r.get(f"{clave}_aws_ambiente") or "").upper()
                ultima_subida = (
                    f'<span class="aws-chip">{ICON_OK} <b>{html.escape(_amb_prev)}</b> · '
                    f'{html.escape(r[f"{clave}_aws_por"])} · {_fecha}</span>'
                )

            col_titulo, col_refresh = st.columns([0.82, 0.18], vertical_alignment="center")
            with col_titulo:
                st.markdown(f'<div class="aws-card-title" style="margin-top:6px">{icono} {label}</div>', unsafe_allow_html=True)
            with col_refresh:
                if st.button(
                    "", key=f"aws_console_refresh_{clave}", icon=MI_REFRESH,
                    help=f"Relee el {label} del disco y recalcula sus validaciones",
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

            if not comp["es_activo"]:
                st.markdown(f"""
                <div class="aws-alert" style="background:#EFF6FF;border-color:#BFDBFE;color:#1E40AF">
                    <b>{ICON_WARNING} No es el UDZ activo:</b> este archivo no está siendo validado ahora mismo.
                    Elegilo en <b>"UDZ a usar"</b> (arriba, en el detalle de la HU) para validarlo antes de subirlo.
                </div>
                """, unsafe_allow_html=True)

            if estado["motivos"]:
                alerta_items = "".join(
                    f"<div style='margin-top:3px'>• <code>{html.escape(m)}</code>: {html.escape(val.get(m, {}).get('detalle', ''))}</div>"
                    for m in estado["motivos"]
                )
                st.markdown(f"""
                <div class="aws-alert">
                    <b>{ICON_WARNING} No está listo para subir ({len(estado['motivos'])}):</b>
                    {alerta_items}
                </div>
                """, unsafe_allow_html=True)

            if estado["amb_motivo"]:
                st.markdown(f"""
                <div class="aws-alert" style="background:#FEE2E2;border-color:#FCA5A5;color:#991B1B">
                    <b>{ICON_ERROR} Ambiente no coincide:</b> {html.escape(estado['amb_motivo'])}
                </div>
                """, unsafe_allow_html=True)

            if estado["archivo_perdido"]:
                st.markdown(f"""
                <div class="aws-alert" style="background:#FEE2E2;border-color:#FCA5A5;color:#991B1B">
                    <b>{ICON_ERROR} El archivo ya no está en disco</b> — puede haberse movido, borrado, o
                    falló al descomprimirse. Apretá el ícono de actualizar (arriba) para resincronizar.
                </div>
                """, unsafe_allow_html=True)

            if archivo:
                _render_contenido(Path(archivo), clave)

            with st.container(key=f"aws_subir_wrap_{clave}"):
                if st.button(
                    f"Subir {comp['label_corto']}", key=f"aws_console_subir_{clave}", width='stretch',
                    icon=MI_CLOUD, disabled=not estado["puede_subir"], help=estado["ayuda"],
                ):
                    with st.spinner(f"Subiendo {label} a {ambiente.upper()}..."):
                        resultado = subir_componente(comp["tipo_tabla"], Path(archivo), ambiente=ambiente)
                    _agregar_al_log(label, ambiente, resultado)
                    if resultado.get("ok"):
                        _persistir_subida_aws(r, clave, ambiente, resultado.get("tabla"), resultados)
                    st.rerun()

    # Feedback del último intento (individual o masivo) — antes solo se veía
    # en el log de la consola, más abajo; con una HU con varios componentes
    # había que bajar a buscarlo para saber si funcionó o no.
    _ultimo = st.session_state.get("_aws_ultimo_resultado")
    if _ultimo:
        if _ultimo["ok"]:
            st.success(
                f"{_ultimo['label']} subido a {_ultimo['ambiente'].upper()} — {_ultimo['en']}",
                icon=MI_OK,
            )
        else:
            st.error(
                f"Falló la subida de {_ultimo['label']} a {_ultimo['ambiente'].upper()} ({_ultimo['en']}) — detalle abajo en la consola",
                icon=MI_ERROR,
            )

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    _render_consola(st.session_state.get("aws_console_log", []))
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    if st.button("Limpiar consola", key="aws_console_limpiar"):
        st.session_state["aws_console_log"] = []
        st.session_state.pop("_aws_ultimo_resultado", None)
        st.rerun()
