"""Selector de HU y todo su panel de detalle: header, trazabilidad/aprobación,
RNF, guía contextual, las 12 validaciones críticas (TA/AID/UDZ y cruzadas),
resumen corto y archivos y adjuntos.

Es el módulo más grande de ui/ porque las 12 validaciones comparten los
helpers val_card/val_group y variables locales del análisis de la HU
seleccionada — partirlas en un archivo por validación sería más archivos
para navegar sin ganar claridad real.
"""
import re
import json
from pathlib import Path
from datetime import datetime

import streamlit as st

from core.config import (
    ICON_OK, ICON_ERROR, ICON_WARNING, ICON_NA, ESTADO_ICON, ESTADO_LISTO,
    KAFKA_TOPIC_REQUERIDO, ROOT_FOLDER, VALIDATION_KEYS, AID_TYPE_VALIDOS,
    MI_APPROVE, MI_ERROR, MI_FILE, MI_GUIDE, MI_INFO, MI_OK, MI_REFRESH, MI_WARNING,
)
from core.analysis import get_estado_code, cargar_json, clasificar_udz_desde_json, normalizar_s3, _val_ok, analizar_hu
from core.utils import abrir_archivo, obtener_usuario_actual
from core.guide import mostrar_guia_tipo


def render_hu_detail(resultados, sprint_activo):
    #  Detalle técnico CON ACORDEONES 
    _last_analyzed = st.session_state.get("_last_analyzed", "")
    _sprint_label  = sprint_activo.split("_")[-1] if sprint_activo else ""
    _snum_match    = re.search(r"Sprint\s*(\d+)", sprint_activo, re.IGNORECASE)
    _sprint_label  = f"Sprint {_snum_match.group(1)}" if _snum_match else sprint_activo

    if not resultados:
        st.stop()

    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <div style="font-size:18px;font-weight:800;color:#2C2A29">Análisis Técnico Detallado</div>
        <div style="font-size:12px;color:#78716C">
            <b>{_sprint_label}</b>
            {"&nbsp;&nbsp;" + ICON_OK + " Analizado: <b>" + _last_analyzed + "</b>" if _last_analyzed else "&nbsp;&nbsp;" + ICON_WARNING + " <span style='color:#B45309'>Sin analizar en esta sesión — presiona Re-analizar para refrescar</span>"}
        </div>
    </div>
    """, unsafe_allow_html=True)

    def _hu_label(r):
        _id    = r.get('hu_id', '?')
        _title = r.get('hu_title', '')[:30]
        _tipo  = r.get('tipo_cambio', '')[:4]  # DESP / MODI
        _icon  = ESTADO_ICON.get(get_estado_code(r), ICON_WARNING)
        return f"{_icon} {_id} — {_title} [{_tipo}]"

    hu_options = {_hu_label(r): r for r in resultados}
    if not hu_options:
        st.warning("No hay HU para mostrar con los filtros seleccionados")
        st.stop()

    seleccion  = st.selectbox("Selecciona una HU para ver detalles", list(hu_options.keys()), key="hu_select")

    if seleccion:
        r   = hu_options[seleccion]
        val = r.get("validaciones", {})

        # Obtener hu_folder para el botn de abrir carpeta
        sprint_path = Path(ROOT_FOLDER) / sprint_activo
        hu_folder = None
        hu_id_str = str(r.get("hu_id", ""))

        if sprint_path.exists():
            for d in sprint_path.iterdir():
                if not d.is_dir():
                    continue
                if d.name.startswith(hu_id_str):
                    hu_folder = d
                    break

        #  Header de HU seleccionada 
        arcs_h = r.get("archivos", {})
        amb_h  = r.get("validaciones", {}).get("ambiente", {}).get("ambiente", "?")
        tipo_h = r.get("tipo_cambio", "?")

        def _arc_chip(key, color):
            val = arcs_h.get(key, " NO EXISTE")
            ok  = "NO" not in val
            icon = ICON_OK if ok else ICON_ERROR
            name = val if ok else "no encontrado"
            c = color if ok else "#DC2626"
            return f'<span class="hu-chip" style="border-color:{c};color:{c}" title="{name}"><b>{key}</b> {icon} <small style="font-weight:400;color:#6B7280">{name[:28]}</small></span>'

        col_header, col_refresh = st.columns([0.85, 0.15], vertical_alignment="center")
        with col_header:
            st.markdown(f"""
            <div class="hu-detail-header">
                <div style="width:100%">
                    <div class="hu-detail-id">HU {r.get('hu_id')}  {tipo_h}</div>
                    <div class="hu-detail-title">{r.get('hu_title','')}</div>
                    <div class="hu-detail-chips">
                        <span class="hu-chip">Estado <b>{r.get('estado_general','')}</b></span>
                        <span class="hu-chip">Ambiente <b>{amb_h}</b></span>
                        {_arc_chip('TA',  '#0369A1')}
                        {_arc_chip('AID', '#7C3AED')}
                        {_arc_chip('UDZ', '#065F46')}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with col_refresh:
            if st.button("Actualizar", key=f"refresh_{r.get('hu_id')}", width='stretch', icon=MI_REFRESH, help="Relee los JSON y recalcula validaciones"):
                if hu_folder:
                    nuevo = analizar_hu(hu_folder)
                    _res = st.session_state.get("resultados", [])
                    for _i, _x in enumerate(_res):
                        if str(_x.get("hu_id")) == str(r.get("hu_id")):
                            _res[_i] = nuevo
                            break
                    st.session_state["resultados"] = _res
                    st.rerun()

        #  Trazabilidad y aprobación para PDN
        _analizado_por     = r.get("analizado_por")
        _analizado_en_fmt  = r.get("analizado_en", "")[:16].replace("T", " ")
        _aprobado_por      = r.get("aprobado_por")
        _aprobado_en_fmt   = r.get("aprobado_en", "")[:16].replace("T", " ")
        _aprobado_estado   = r.get("aprobado_estado_code")
        _estado_code_hoy   = get_estado_code(r)

        if _analizado_por:
            st.caption(f"Último análisis: {_analizado_por} — {_analizado_en_fmt}")

        _aprobacion_vigente = bool(_aprobado_por) and _aprobado_estado == _estado_code_hoy == ESTADO_LISTO

        if _aprobado_por and not _aprobacion_vigente:
            st.warning(
                f"Se aprobó por {_aprobado_por} el {_aprobado_en_fmt}, pero el análisis cambió desde entonces — revisar antes de confiar en esta aprobación",
                icon=MI_WARNING,
            )

        if _aprobacion_vigente:
            st.success(f"Aprobado para PDN por {_aprobado_por} — {_aprobado_en_fmt}", icon=MI_APPROVE)
        else:
            _puede_aprobar = _estado_code_hoy == ESTADO_LISTO
            if st.button("Marcar como aprobado para PDN", key=f"aprobar_{r.get('hu_id')}", width='stretch',
                         icon=MI_APPROVE, disabled=not _puede_aprobar,
                         help="Solo se puede aprobar si el estado actual es LISTO" if not _puede_aprobar else None):
                if hu_folder:
                    r["aprobado_por"] = obtener_usuario_actual()
                    r["aprobado_en"] = datetime.now().isoformat()
                    r["aprobado_estado_code"] = _estado_code_hoy
                    out_path = hu_folder / "analisis" / "analisis_tecnico.json"
                    out_path.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
                    _res = st.session_state.get("resultados", [])
                    for _i, _x in enumerate(_res):
                        if str(_x.get("hu_id")) == str(r.get("hu_id")):
                            _res[_i] = r
                            break
                    st.session_state["resultados"] = _res
                    st.success("Aprobación registrada", icon=MI_OK)
                    st.rerun()

        #  SECCIÓN DE RNF
        rnf_path_str = r.get("rnf_path")
        rnf_path = Path(rnf_path_str) if rnf_path_str else None

        col_rnf1, col_rnf2 = st.columns([0.75, 0.25], vertical_alignment="center")
        with col_rnf1:
            if rnf_path:
                st.markdown(f"""
                <div class="rnf-card ok">
                    <div class="rnf-icon">{ICON_OK}</div>
                    <div>
                        <div class="rnf-info-title">RNF encontrado</div>
                        <div class="rnf-info-sub"><code>{rnf_path.name}</code> — Copia los datos al consolidado antes de proceder</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="rnf-card miss">
                    <div class="rnf-icon">{ICON_ERROR}</div>
                    <div>
                        <div class="rnf-info-title">Falta el RNF</div>
                        <div class="rnf-info-sub">No se encontró archivo RNF*.xlsx — Revisa los adjuntos en ADO y descarga nuevamente</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        with col_rnf2:
            if rnf_path:
                if st.button("Abrir RNF", key=f"btn_rnf_{r.get('hu_id')}", width='stretch'):
                    abrir_archivo(rnf_path)
            else:
                st.button("RNF no disponible", disabled=True, key=f"btn_rnf_dis_{r.get('hu_id')}", width='stretch')

        st.divider()

        #  BLOQUE UDZ DETECTADOS (si hay múltiples) 
        udz_files_raw = r.get("udz_files", []) if isinstance(r.get("udz_files"), list) else []
        udz_files = [Path(p) if isinstance(p, str) else p for p in udz_files_raw]
        if udz_files and len(udz_files) > 1:
            st.markdown("### UDZ Detectados en esta HU")
            cols = st.columns(len(udz_files))
            for idx, udz_path in enumerate(udz_files):
                with cols[idx]:
                    udz_data = cargar_json(udz_path)
                    tipo_udz = clasificar_udz_desde_json(udz_data) if udz_data else "DESCONOCIDO"
                    color = "#059669" if tipo_udz == "RESULTADOS" else "#0369A1" if tipo_udz == "CRUDOS" else "#78716C"

                    if udz_data:
                        item = udz_data.get("item", udz_data)
                        req = str(item.get("require_transmission", "")).strip().lower()
                        emit = str(item.get("emit_event", "")).strip().lower()
                        s3p = item.get("s3_path", "")
                    else:
                        req, emit, s3p = "?", "?", "?"

                    st.markdown(f"""
                    <div style="border:2px solid {color};border-radius:8px;padding:12px;background:#FAFAF9">
                        <div style="font-weight:700;font-size:13px;color:{color}">{tipo_udz}</div>
                        <div style="font-size:11px;color:#6B7280;margin-top:6px;word-break:break-all">
                            <code>{udz_path.name}</code><br>
                            <span style="color:#374151">require_transmission: <strong>{req}</strong></span><br>
                            <span style="color:#374151">emit_event: <strong>{emit}</strong></span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            st.divider()

        #  Alerta de archivos con nombre genérico (visible siempre) 
        _configs_alerta = r.get("configs_sin_tipo", [])
        if _configs_alerta:
            for cfg in _configs_alerta:
                _nombre = cfg["nombre"]
                _tipo   = cfg["tipo_inferido"]
                _auto   = cfg.get("auto_asignado", False)
                _color  = {"AID": "#7C3AED", "TA": "#0369A1", "UDZ": "#065F46"}.get(_tipo, "#92400E")
                if _tipo != "desconocido":
                    st.markdown(f"""
                    <div style="border-left:4px solid {_color};background:#FFFBEB;padding:10px 14px;border-radius:0 6px 6px 0;margin:4px 0">
                        <div style="font-weight:700;font-size:12px;color:#92400E">{ICON_WARNING} ARCHIVO CON NOMBRE GENÉRICO — REQUIERE REVISIÓN MANUAL</div>
                        <div style="font-size:12px;color:#374151;margin-top:4px">
                            <code>{_nombre}</code> fue detectado como <strong style="color:{_color}">{_tipo}</strong> por su estructura interna,
                            pero <strong>debes abrirlo y confirmar</strong> que realmente corresponde a ese componente.
                            El nombre del archivo debe empezar con <code>{"ta_" if _tipo=="TA" else "aid_" if _tipo=="AID" else "udz_"}</code> para ser detectado automáticamente en futuras revisiones.
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div style="border-left:4px solid #DC2626;background:#FEF2F2;padding:10px 14px;border-radius:0 6px 6px 0;margin:4px 0">
                        <div style="font-weight:700;font-size:12px;color:#DC2626">{ICON_ERROR} ARCHIVO NO RECONOCIDO — REVISIÓN OBLIGATORIA</div>
                        <div style="font-size:12px;color:#374151;margin-top:4px">
                            <code>{_nombre}</code> no pudo identificarse como TA, AID ni UDZ.
                            <strong>ábrelo manualmente</strong> y determina a qué componente pertenece.
                            Renómbralo con <code>ta_</code>, <code>aid_</code> o <code>udz_</code> para que sea procesado correctamente.
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

        #  P0: GUÍA CONTEXTUALIZADA 
        with st.expander("GUÍA: Cómo Analizar Esta HU", expanded=False, icon=MI_GUIDE):
            guia = mostrar_guia_tipo(r.get("tipo_cambio", "DESPLIEGUE"))
            st.markdown(guia)

        st.divider()

        #  Validaciones críticas 
        # Nombres de archivo detectados
        _arcs    = r.get("archivos", {})
        _f_ta    = _arcs.get("TA",  "TA")
        _f_aid   = _arcs.get("AID", "AID")
        _f_udz   = _arcs.get("UDZ", "UDZ")

        # Pre-calcular todos los estados
        s3_info  = val.get("s3_path", {});          s3_ok  = s3_info.get("ok", False);   s3_na  = s3_info.get("na", False)
        wf_info  = val.get("workflow_vs_id", {});   wf_ok  = wf_info.get("ok", False);   wf_na  = wf_info.get("na", False)
        kf_info  = val.get("kafka", {});            kf_ok  = kf_info.get("ok", False);   kf_na  = kf_info.get("na", False)
        coh_info = val.get("coherencia", {});       coh_ok = coh_info.get("ok", False);  coh_na = coh_info.get("na", False)
        ls_info  = val.get("last_step", {});        ls_ok  = ls_info.get("ok", False);   ls_na  = ls_info.get("na", False)
        oz_info  = val.get("out_zone_copiar", {})
        oz_ok    = oz_info.get("out_zone_ok", False) and oz_info.get("copiar_ok", False)
        oz_na    = oz_info.get("na", False)
        ta_cu_info = val.get("ta_cu_name", {});           ta_cu_ok = ta_cu_info.get("ok", False); ta_cu_na = ta_cu_info.get("na", False)
        ta_tp_info = val.get("ta_type_prompts", {});      ta_tp_ok = ta_tp_info.get("ok", False); ta_tp_na = ta_tp_info.get("na", False)
        aid_tec_info = val.get("aid_tecnologia", {});     aid_tec_ok = aid_tec_info.get("ok", False); aid_tec_na = aid_tec_info.get("na", False)
        aid_type_info = val.get("aid_type_topic", {});    aid_type_ok = aid_type_info.get("ok", False); aid_type_na = aid_type_info.get("na", False)
        amb_wf_info = val.get("ambiente_workflow_id", {}); amb_wf_ok = amb_wf_info.get("ok", False); amb_wf_na = amb_wf_info.get("na", False)
        udz_tx_info = val.get("udz_transmisiones", {});   udz_tx_ok = udz_tx_info.get("ok", False); udz_tx_na = udz_tx_info.get("na", False)

        # Conteo robusto: recorre la misma lista canónica de claves que usa analizar_hu,
        # así el resumen nunca puede desincronizarse de la lógica real de estado_code.
        n_na  = sum(1 for k in VALIDATION_KEYS if val.get(k, {}).get("na", False))
        n_ok  = sum(1 for k in VALIDATION_KEYS if not val.get(k, {}).get("na", False) and _val_ok(val.get(k, {})))
        n_err = len(VALIDATION_KEYS) - n_na - n_ok

        # Título del expander — solo muestra N/A si hay alguno
        _parts = []
        if n_ok:  _parts.append(f"{ICON_OK} {n_ok} correctas")
        if n_err: _parts.append(f"{ICON_ERROR} {n_err} con error")
        if n_na:  _parts.append(f"{ICON_NA} {n_na} no aplican")
        _exp_label = "Validaciones críticas — " + ("  ·  ".join(_parts) if _parts else "sin datos")

        with st.expander(_exp_label, expanded=True):
            st.markdown(
                "Verifica la conexión entre **TA** (Text Analyzer — extracción), **AID** (configuración) y **UDZ** (eventos). "
                "Los tres deben estar alineados para que el flujo funcione en producción."
            )

            #  Contador visual 
            st.markdown(f"""
            <div class="val-summary">
                <div class="val-summary-item">
                    <div class="val-summary-dot ok"></div>{n_ok} correctas
                </div>
                <div class="val-summary-item">
                    <div class="val-summary-dot err"></div>{n_err} con error
                </div>
                <div class="val-summary-item">
                    <div class="val-summary-dot" style="background:#78716C;width:10px;height:10px;border-radius:50%;display:inline-block"></div>&nbsp;{n_na} no aplican
                </div>
            </div>
            """, unsafe_allow_html=True)

            def val_group(nombre):
                """Encabezado de grupo: agrupa las tarjetas por dónde hay que mirar (TA/AID/UDZ/cruzadas)."""
                st.markdown(f"<div class='val-group-title'>{nombre}</div>", unsafe_allow_html=True)

            #  Helper inline para renderizar cada card
            def val_card(estado, titulo, archivo, regla, detalle_fn, na=False, campo=None, valor_ok=None):
                if na:
                    _cls = "na"; _mark = ICON_NA; _color = "#78716C"
                    _regla_txt = "<span style='color:#78716C;font-style:italic'>No aplica — archivo no presente en esta modificación</span>"
                else:
                    _cls   = "ok" if estado else "err"
                    _mark  = ICON_OK if estado else ICON_ERROR
                    _color = "#15803D" if estado else "#B91C1C"
                    _regla_txt = regla
                _campo_html = f'<code class="val-card-field">{campo}</code>' if campo and not na else ""
                _valor_html = f'<span class="val-card-valor">→ {valor_ok}</span>' if (estado and valor_ok and not na) else ""
                st.markdown(f"""
                <div class="val-card {_cls}" style="{'opacity:0.55' if na else ''}">
                    <div class="val-card-header">
                        <div class="val-card-title">
                            <span style="color:{_color};font-weight:800;font-size:15px">{_mark}</span>
                            {titulo} {_campo_html}
                        </div>
                        <span class="val-card-file">{archivo}</span>
                    </div>
                    <div class="val-card-sub">{_regla_txt}{_valor_html}</div>
                </div>
                """, unsafe_allow_html=True)
                if not estado and not na:
                    detalle_fn()

            #  Grupo TA
            val_group("TA — Text Analyzer (extracción)")

            ta_cu_val = ta_cu_info.get("cu_name", "")
            def _ta_cu_detail():
                st.markdown("**TA cu_name encontrado:**")
                st.code(ta_cu_val or "(vacío)", language="text")
                st.markdown("**Regla:** Obligatorio en TA, identifica el caso de uso de forma única")
                if not ta_cu_val:
                    st.error(f"{ICON_ERROR} **cu_name falta**")
                    st.info('**Agregar en TA** → en la raíz o dentro de `item`:\n```json\n"cu_name": "ta_<mi_caso_uso>"\n```')
            val_card(ta_cu_ok, "cu_name obligatorio", _f_ta,
                     "TA siempre debe incluir cu_name para identificar el caso de uso", _ta_cu_detail,
                     na=ta_cu_na, campo="TA.cu_name", valor_ok=ta_cu_val)

            ta_type_val = ta_tp_info.get("type", "")
            def _ta_type_detail():
                st.markdown("**TA type encontrado:**")
                st.code(str(ta_type_val) or "(vacío)", language="text")
                st.markdown("**Regla:** Estructura TA debe declarar `type: \"prompts\"` en la raíz")
                if not ta_type_val:
                    st.error(f"{ICON_ERROR} **type no encontrado**")
                    st.info('**Agregar en TA** → en la raíz:\n```json\n"type": "prompts"\n```')
                elif str(ta_type_val).lower() != "prompts":
                    st.error(f"{ICON_ERROR} **type inválido: {ta_type_val}** (debe ser 'prompts')")
            val_card(ta_tp_ok, "type = prompts", _f_ta,
                     "Estructura TA debe declarar type='prompts' como patrón de extracción", _ta_type_detail,
                     na=ta_tp_na, campo="TA.type", valor_ok=ta_type_val)

            topic_vals = kf_info.get("topics", [])
            topic = kf_info.get("topic", "")
            def _kf_detail():
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Topic requerido (corporativo):**")
                    st.code(KAFKA_TOPIC_REQUERIDO, language="text")
                with col2:
                    st.markdown("**Topic(s) encontrado(s) en TA:**")
                    st.code("\n".join(topic_vals) if topic_vals else "(no encontrado)", language="text")
                st.markdown("**Regla:** Todos los TA deben publicar en el topic corporativo de ingesta (si hay varios steps, todos deben coincidir)")
                if not topic_vals:
                    st.error(f"{ICON_ERROR} **kafka_output_topic no encontrado**")
                    st.info(f'**Agregar en TA** → dentro de `data` o al nivel principal:\n```json\n"kafka_output_topic": "{KAFKA_TOPIC_REQUERIDO}"\n```')
                else:
                    st.error(f"{ICON_ERROR} **Topic incorrecto en {sum(1 for t in topic_vals if t != KAFKA_TOPIC_REQUERIDO)} de {len(topic_vals)} ocurrencia(s)**")
                    st.info(f'**Cambiar en TA** → `Ctrl+F: kafka_output_topic`\n```json\n"kafka_output_topic": "{KAFKA_TOPIC_REQUERIDO}"\n```')
            val_card(kf_ok, "Kafka output topic", _f_ta,
                     "TA debe publicar en topic corporativo de recepción documental", _kf_detail,
                     na=kf_na, campo="TA...kafka_output_topic", valor_ok=topic)

            #  Grupo AID
            val_group("AID — configuración")

            aid_tec_val = aid_tec_info.get("tecnologia", "")
            def _aid_tec_detail():
                st.markdown("**AID workflow_variables.tecnologia encontrado:**")
                st.code(str(aid_tec_val) or "(vacío)", language="text")
                st.markdown("**Regla:** Obligatorio en AID, identifica que la orquestación es por AID")
                if not aid_tec_val:
                    st.error(f"{ICON_ERROR} **tecnologia no encontrada**")
                    st.info('**Agregar en AID** → dentro de `workflow_variables`:\n```json\n"workflow_variables": {"tecnologia": "AID"}\n```')
            val_card(aid_tec_ok, "tecnologia = AID", _f_aid,
                     "AID debe declarar workflow_variables.tecnologia='AID'", _aid_tec_detail,
                     na=aid_tec_na, campo="AID.workflow_variables.tecnologia", valor_ok=aid_tec_val)

            aid_type_vals = aid_type_info.get("types", [])
            aid_type_val  = aid_type_info.get("type", "")
            _aid_type_validos_txt = " / ".join(sorted(AID_TYPE_VALIDOS))
            def _aid_type_detail():
                st.markdown("**TYPE(s) encontrado(s) en AID:**")
                st.code("\n".join(str(t) for t in aid_type_vals) if aid_type_vals else "(vacío)", language="text")
                st.markdown(f"**Regla:** Cada step de workflow debe usar `TYPE` en {{{_aid_type_validos_txt}}} — `topic` para steps que publican evento, `write_results` para un step final que solo escribe/guarda resultados")
                if not aid_type_vals:
                    st.error(f"{ICON_ERROR} **TYPE no encontrado en steps**")
                    st.info('**Agregar en AID steps** → en cada STEP_VARIABLES o step root:\n```json\n"TYPE": "topic"\n```')
                else:
                    _invalidos = sum(1 for t in aid_type_vals if str(t).strip().lower() not in AID_TYPE_VALIDOS)
                    st.error(f"{ICON_ERROR} **TYPE inválido en {_invalidos} de {len(aid_type_vals)} step(s)**")
            val_card(aid_type_ok, f"TYPE ∈ {{{_aid_type_validos_txt}}}", _f_aid,
                     f"Cada step de orquestación debe usar TYPE en {{{_aid_type_validos_txt}}}", _aid_type_detail,
                     na=aid_type_na, campo="AID...TYPE", valor_ok=aid_type_val)

            ls_vals       = ls_info.get("valores", [])
            ls_encontrado = ls_info.get("encontrado", False)
            def _ls_detail():
                st.markdown("**LAST_STEP encontrados en AID:**")
                st.code(str(ls_vals) if ls_vals else "(ninguno)", language="text")
                st.markdown("**Regla:** Todos los pasos del workflow DEBEN tener `LAST_STEP: \"False\"`")
                if ls_encontrado and not ls_ok:
                    st.error(f"{ICON_ERROR} **LAST_STEP no está en False**")
                    st.info('**Cambiar en AID** → `Ctrl+F: LAST_STEP`\n```json\n"LAST_STEP": "False"\n```')
                elif not ls_encontrado:
                    st.warning(f"{ICON_WARNING} **LAST_STEP no encontrado** — Verifica la estructura `workflow_definition` en AID")
            val_card(ls_ok, "LAST_STEP en False", _f_aid,
                     "Todos los pasos del workflow deben cerrar con LAST_STEP=False", _ls_detail,
                     na=ls_na, campo="AID...LAST_STEP", valor_ok=(", ".join(ls_vals) if ls_vals else None))

            oz_vals     = oz_info.get("out_zones", [])
            copiar_vals = oz_info.get("copiar_vals", [])
            conflictos = oz_info.get("conflictos", [])
            def _oz_detail():
                st.markdown("**Configuración encontrada en AID:**")
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**copiarResultadoBucket**")
                    st.code(", ".join(copiar_vals) if copiar_vals else "(no encontrado)", language="text")
                with c2:
                    st.markdown("**out_zone**")
                    st.code(", ".join(oz_vals) if oz_vals else "(no encontrado)", language="text")
                st.markdown("**Regla:** Si existe `out_zone`, debe estar acompañado de `copiarResultadoBucket=true` (y no ambos juntos)")
                if oz_vals and not copiar_vals:
                    st.error(f"{ICON_ERROR} **Conflicto:** out_zone existe pero falta copiarResultadoBucket=true")
                elif conflictos:
                    st.error(f"{ICON_ERROR} **Conflicto:** {conflictos[0]}")
                elif copiar_vals and any(str(v).lower() != "true" for v in copiar_vals):
                    st.error(f"{ICON_ERROR} **copiarResultadoBucket no es true**")
            val_card(oz_ok, "out_zone & copiarResultadoBucket", _f_aid,
                     "Validar configuración de copia de resultados en AID", _oz_detail, na=oz_na,
                     campo="AID...STEP_VARIABLES.{out_zone, copiarResultadoBucket}")

            #  Grupo UDZ
            val_group("UDZ — eventos")

            tx_tipo = udz_tx_info.get("udz_tipo", "NO_DEFINIDO")
            def _udz_tx_detail():
                st.markdown("### UDZ detectados en esta HU:")
                udz_files_list = [Path(p) for p in r.get("udz_files", [])]
                if udz_files_list:
                    for udz_f in udz_files_list:
                        udz_d = cargar_json(udz_f)
                        tipo = clasificar_udz_desde_json(udz_d) if udz_d else "DESCONOCIDO"
                        if udz_d:
                            item = udz_d.get("item", udz_d)
                            req = str(item.get("require_transmission", "")).strip()
                            emit = str(item.get("emit_event", "")).strip()
                            s3 = item.get("s3_path", "(no encontrado)")
                        else:
                            req, emit, s3 = "?", "?", "(JSON inválido)"

                        with st.expander(f"{udz_f.name} — **{tipo}**", expanded=True):
                            c1, c2, c3 = st.columns(3)
                            with c1:
                                st.markdown("**require_transmission**")
                                st.code(req, language="text")
                            with c2:
                                st.markdown("**emit_event**")
                                st.code(emit, language="text")
                            with c3:
                                st.markdown("**tipo esperado**")
                                st.code(tipo, language="text")
                            st.markdown("**s3_path**")
                            st.code(s3, language="text")

                st.markdown("---")
                st.markdown("""
                **Reglas de validación por tipo:**
                - **RESULTADOS**: require_transmission=`true` + emit_event=`false` + s3_path contiene `resultados`
                - **CRUDOS**: require_transmission=`false` + emit_event=`true` + s3_path contiene `crudos`
                """)
            val_card(udz_tx_ok, "Reglas de transmisión (crudos/resultados)", _f_udz,
                     "UDZ debe cumplir las reglas específicas según sea CRUDOS o RESULTADOS", _udz_tx_detail,
                     na=udz_tx_na, campo="UDZ.item.{require_transmission, emit_event, s3_path}",
                     valor_ok=(tx_tipo if tx_tipo != "NO_DEFINIDO" else None))

            #  Grupo cruzadas: TA <-> AID <-> UDZ
            val_group("Cruzadas — TA ↔ AID ↔ UDZ")

            aid_path = s3_info.get("aid", "")
            udz_path = s3_info.get("udz", "")
            def _s3_detail():
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**AID s3_path encontrado:**")
                    st.code(aid_path or "(vacío)", language="text")
                with col2:
                    st.markdown("**UDZ s3_path encontrado:**")
                    st.code(udz_path or "(vacío)", language="text")
                st.markdown("**Regla:** Las rutas deben coincidir exactamente (se ignora `/` al final)")
                if aid_path and udz_path and normalizar_s3(aid_path) != normalizar_s3(udz_path):
                    st.error(f"{ICON_ERROR} **Mismatch detectado** — Alinear al valor de UDZ:")
                    st.info(f'**En AID** → `Ctrl+F: s3_path`\n```json\n"s3_path": "{normalizar_s3(udz_path)}"\n```')
            val_card(s3_ok, "S3 Path — AID = UDZ", f"{_f_aid} & {_f_udz}",
                     "Rutas del bucket AID y UDZ deben ser idénticas", _s3_detail,
                     na=s3_na, campo="AID.s3_path ↔ UDZ.item.s3_path", valor_ok=normalizar_s3(aid_path) if aid_path else None)

            wf_val  = wf_info.get("workflow_name", "")
            uid_val = wf_info.get("udz_id", "")
            def _wf_detail():
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**AID workflow_name encontrado:**")
                    st.code(wf_val or "(vacío)", language="text")
                with col2:
                    st.markdown("**UDZ id encontrado:**")
                    st.code(uid_val or "(vacío)", language="text")
                st.markdown("**Regla:** Deben ser exactamente iguales, incluyendo ambiente (qa/pdn/dev)")
                if wf_val and uid_val and wf_val != uid_val:
                    st.error(f"{ICON_ERROR} **Mismatch detectado**")
                    st.info(f'**Cambiar en AID** → `Ctrl+F: workflow_name`\n```json\n"workflow_name": "{uid_val}"\n```')
            val_card(wf_ok, "workflow_name — AID = UDZ id", f"{_f_aid} & {_f_udz}",
                     "El identificador de orquestación debe coincidir con el ID del evento UDZ", _wf_detail,
                     na=wf_na, campo="AID.workflow_name ↔ UDZ.item.id", valor_ok=wf_val)

            uc = coh_info.get("use_case", "")
            cu = coh_info.get("cu_name", "")
            if not coh_ok:
                _coh_arch = _f_ta if (uc and not cu) else f"{_f_aid} & {_f_ta}"
            else:
                _coh_arch = f"{_f_aid} & {_f_ta}"
            def _coh_detail():
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**AID use_case encontrado:**")
                    st.code(uc or "(vacío)", language="text")
                with col2:
                    st.markdown("**TA cu_name encontrado:**")
                    st.code(cu or "(vacío)", language="text")
                st.markdown("**Regla:** El nombre del caso de uso debe ser idéntico en ambos componentes")
                if uc and cu and uc != cu:
                    st.warning(f'**Alinear en AID** → `Ctrl+F: use_case`\n```json\n"use_case": "{cu}"\n```')
                elif not uc or not cu:
                    st.error(f"{ICON_ERROR} **Falta uno de los dos valores**")
            val_card(coh_ok, "Coherencia — use_case = cu_name", _coh_arch,
                     "Nombre del caso de uso debe ser igual en AID y TA para trazabilidad", _coh_detail,
                     na=coh_na, campo="AID.use_case ↔ TA.cu_name", valor_ok=uc)

            aid_amb = amb_wf_info.get("aid_ambiente", "DESCONOCIDO")
            udz_amb = amb_wf_info.get("udz_ambiente", "DESCONOCIDO")
            wf_name = amb_wf_info.get("aid_workflow_name", "")
            udz_id = amb_wf_info.get("udz_id", "")
            def _amb_wf_detail():
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**AID workflow_name encontrado:**")
                    st.code(wf_name or "(vacío)", language="text")
                    st.caption(f"Ambiente detectado: **{aid_amb}**")
                with c2:
                    st.markdown("**UDZ id encontrado:**")
                    st.code(udz_id or "(vacío)", language="text")
                    st.caption(f"Ambiente detectado: **{udz_amb}**")
                st.markdown("**Regla:** Ambos deben apuntar al mismo ambiente (qa, pdn, dev)")
                if aid_amb != udz_amb and aid_amb != "DESCONOCIDO" and udz_amb != "DESCONOCIDO":
                    st.error(f"{ICON_ERROR} **Mismatch de ambiente:** AID={aid_amb} pero UDZ={udz_amb}")
            val_card(amb_wf_ok, "Ambiente — workflow_name = id (qa/pdn/dev)", f"{_f_aid} & {_f_udz}",
                     "AID y UDZ deben apuntar al mismo ambiente operativo", _amb_wf_detail,
                     na=amb_wf_na, campo="AID.workflow_name ↔ UDZ.item.id",
                     valor_ok=(aid_amb if aid_amb != "DESCONOCIDO" else None))

        #  Resumen corto: qué se encontró y qué falta (antes de Archivos y adjuntos)
        _arcs_r = r.get("archivos", {})
        _presentes  = [k for k in ("TA", "AID", "UDZ") if "NO" not in _arcs_r.get(k, "NO")]
        _faltan_arc = [k for k in ("TA", "AID", "UDZ") if "NO" in _arcs_r.get(k, "NO")]
        if r.get("rnf_path"):
            _presentes.append("RNF")
        else:
            _faltan_arc.append("RNF")

        _falta_partes = []
        if _faltan_arc:
            _falta_partes.append(", ".join(_faltan_arc))
        if n_err:
            _falta_partes.append(f"{n_err} validación(es) con error — ver arriba")
        _falta_txt = " · ".join(_falta_partes) if _falta_partes else "Nada — todo lo esperado está presente y correcto"
        _hay_algo_falta = bool(_faltan_arc) or bool(n_err)

        _notas = r.get("resumen", [])
        _notas_html = ""
        if _notas:
            _notas_html = (
                "<div style='margin-top:6px;padding-top:6px;border-top:1px solid rgba(0,0,0,.08);"
                "font-size:11px;color:#78716C;font-style:italic;line-height:1.5'>"
                + "<br>".join(_notas) + "</div>"
            )

        col_found, col_missing = st.columns(2)
        with col_found:
            st.markdown(f"""
            <div class="resumen-box ok">
                <div class="resumen-box-title">{ICON_OK} Encontrado</div>
                <div class="resumen-box-body">{", ".join(_presentes) if _presentes else "Ningún archivo detectado"}</div>
            </div>
            """, unsafe_allow_html=True)
        with col_missing:
            st.markdown(f"""
            <div class="resumen-box {'err' if _hay_algo_falta else 'ok'}">
                <div class="resumen-box-title">{ICON_WARNING if _hay_algo_falta else ICON_OK} Falta</div>
                <div class="resumen-box-body">{_falta_txt}</div>{_notas_html}
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        with st.expander("Archivos y adjuntos", expanded=False, icon=MI_FILE):
            arcs = r.get("archivos", {})
            st.markdown("**Componentes técnicos**")

            for comp, archivo in arcs.items():
                ok = "NO" not in archivo
                if ok:
                    st.markdown(f"{ICON_OK} **{comp}**: `{archivo}`")
                else:
                    st.error(f"**{comp}**: NO ENCONTRADO", icon=MI_ERROR)

            #  Alerta config.json sin nombre descriptivo
            configs_sin_tipo = r.get("configs_sin_tipo", [])
            if configs_sin_tipo:
                st.markdown("---")
                st.markdown("**Archivos con nombre genérico detectados**")
                for cfg in configs_sin_tipo:
                    nombre = cfg["nombre"]
                    tipo   = cfg["tipo_inferido"]
                    auto   = cfg.get("auto_asignado", False)
                    _color = {"AID": "#7C3AED", "TA": "#0369A1", "UDZ": "#065F46"}.get(tipo, "#92400E")
                    _estado = f"{ICON_OK} Auto-asignado como componente" if auto else f"{ICON_WARNING} Tipo no reconocido — revisa manualmente"
                    _nota = (f"Fue asignado automáticamente al slot <strong>{tipo}</strong> para análisis."
                             if auto else
                             "No se pudo determinar el tipo. Renombra el archivo con <code>ta_</code>, <code>aid_</code> o <code>udz_</code> en el nombre.")
                    st.markdown(f"""
                    <div style="border:1px solid {_color};border-radius:6px;padding:10px 14px;margin:6px 0;background:#FAFAFA">
                        <div style="font-weight:600;font-size:13px"><code>{nombre}</code>
                            <span style="font-size:11px;color:{_color};margin-left:8px">{_estado} <strong>{tipo if auto else ''}</strong></span>
                        </div>
                        <div style="font-size:11px;color:#6B7280;margin-top:5px">{_nota}</div>
                    </div>
                    """, unsafe_allow_html=True)

            atts = r.get("attachments", [])
            if atts:
                st.markdown(f"**Adjuntos descargados ({len(atts)})**")
                for a in atts:
                    icon = ICON_OK if a.get("downloaded") else ICON_ERROR
                    status = "Descargado" if a.get("downloaded") else "Error"
                    st.markdown(f"{icon} **{a.get('name','')}** — {status}")
            else:
                st.info("No hay adjuntos descargados", icon=MI_INFO)

            if r.get("downloaded_at"):
                st.markdown(f"**Fecha de descarga:** {r['downloaded_at'][:19]}")
