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
import html
from pathlib import Path
from datetime import datetime

import streamlit as st

from core.config import (
    ICON_OK, ICON_ERROR, ICON_WARNING, ICON_NA, ESTADO_ICON, ESTADO_LISTO, ESTADO_ERROR,
    KAFKA_TOPIC_REQUERIDO, ROOT_FOLDER, VALIDATION_KEYS, AID_TYPE_VALIDOS,
    MI_APPROVE, MI_GUIDE, MI_OK, MI_REFRESH, MI_WARNING, MI_SUMMARY, MI_INFO, MI_SEARCH,
)
from core.analysis import get_estado_code, cargar_json, clasificar_udz_desde_json, normalizar_s3, _val_ok, analizar_hu, detectar_slots_udz, obtener_estado_pdn_real
from core.utils import abrir_archivo, obtener_usuario_actual
from core.guide import mostrar_guia_tipo


def _generar_resumen_resolution(r: dict) -> tuple:
    """Texto para copiar al Resolution de la HU en ADO, con el estado real
    del flujo (QA, AWS, PDN). Un componente sin archivo en esta HU se marca
    "no aplica", no "no subido". Devuelve (texto, completo)."""
    estado_code = get_estado_code(r)
    estado_txt = {ESTADO_LISTO: "LISTO", ESTADO_ERROR: "CON ERRORES"}.get(estado_code, "INCOMPLETO")

    lineas = [
        f"HU {r.get('hu_id', '?')} — {r.get('hu_title', '')}",
        f"Estado de Flujo: {estado_txt}",
        "",
    ]

    # Un solo cálculo de slots UDZ, reusado acá (referencia técnica) y más
    # abajo (checklist) — si hay crudos y resultados como archivos separados,
    # cada uno tiene su propio s3_path y no alcanza con mostrar uno solo.
    _slots_udz = detectar_slots_udz(r)

    # Referencia técnica solo una vez que la HU YA se subió de verdad a PDN
    # (no apenas se detecta que los archivos son "de PDN" por su s3_path) —
    # antes de subir no hay nada que referenciar todavía.
    _val = r.get("validaciones", {})
    if obtener_estado_pdn_real(r)["desplegado"]:
        _cu_name = _val.get("ta_cu_name", {}).get("cu_name") or ""
        _aid_s3  = _val.get("s3_path", {}).get("aid") or ""
        _hay_ref = bool(_cu_name or _aid_s3)
        if _cu_name:
            lineas.append(f"🔗 TA cu_name: {_cu_name}")
        if _aid_s3:
            lineas.append(f"🔗 AID s3_path: {_aid_s3}")
        if len(_slots_udz) == 1:
            _udz_s3 = _val.get("s3_path", {}).get("udz") or ""
            if _udz_s3:
                lineas.append(f"🔗 UDZ s3_path: {_udz_s3}")
                _hay_ref = True
        else:
            # Solo el UDZ activo pasa por las validaciones — para el otro se
            # lee el s3_path directo del archivo, sin pasar por "val".
            _nombres_s3 = {"CRUDOS": "Crudos", "RESULTADOS": "Transmisión"}
            for _s in _slots_udz:
                _data = cargar_json(Path(_s["archivo"])) if _s["archivo"] else None
                _item = _data.get("item", _data) if isinstance(_data, dict) else {}
                _path = _item.get("s3_path", "") if isinstance(_item, dict) else ""
                if _path:
                    _nombre = _nombres_s3.get(_s["tipo"], _s["tipo"] or "?")
                    lineas.append(f"🔗 UDZ s3_path ({_nombre}): {_path}")
                    _hay_ref = True
        if _hay_ref:
            lineas.append("")

    _qa_por = r.get("probado_qa_por")
    if _qa_por:
        _qa_en = (r.get("probado_qa_en") or "")[:16].replace("T", " ")
        lineas.append(f"✅ Probado en QA — {_qa_por} — {_qa_en}")
    else:
        # ➖ (no ❌): probar en QA es opcional, no un requisito que falte.
        lineas.append("➖ No se registró prueba en QA")

    def _linea_aws(clave, nombre, hay_archivo):
        if not hay_archivo:
            lineas.append(f"➖ {nombre} no aplica en esta HU")
            return
        _por = r.get(f"{clave}_aws_por")
        if _por:
            _amb = (r.get(f"{clave}_aws_ambiente") or "").upper()
            _en = (r.get(f"{clave}_aws_en") or "")[:16].replace("T", " ")
            lineas.append(f"✅ {nombre} subido a {_amb} — {_por} — {_en}")
        else:
            lineas.append(f"❌ {nombre} no subido a AWS")

    _linea_aws("ta", "TA", bool(r.get("ta_activo")))
    _linea_aws("aid", "AID", bool(r.get("aid_activo")))

    if len(_slots_udz) == 1:
        _s = _slots_udz[0]
        _sub = f" ({_s['tipo']})" if _s["tipo"] else ""
        _linea_aws("udz", f"UDZ{_sub}", bool(_s["archivo"]))
    else:
        _nombres = {"CRUDOS": "UDZ Crudos (entrada)", "RESULTADOS": "UDZ Transmisión (salida)"}
        for _s in _slots_udz:
            _linea_aws(f"udz_{_s['tipo'].lower()}", _nombres.get(_s["tipo"], "UDZ"), True)

    # No hace falta una línea aparte de "Desplegado en PDN": cada línea de
    # arriba ya dice a qué ambiente se subió cada componente — si todas dicen
    # PDN, la HU está desplegada; no hay un hecho adicional que registrar.
    completo = not any(l.startswith("❌") for l in lineas)
    return "\n".join(lineas), completo


# Colores en línea (no clase CSS): al copiar HTML seleccionado del navegador
# solo viaja el style="..." puesto directo en el elemento, no la hoja de
# estilos — sin esto se pegaba todo en negro.
_RESUMEN_COLORES = {"ok": "#065F46", "err": "#991B1B", "na": "#78716C"}


def _resumen_filas_html(texto: str) -> str:
    """Arma las filas HTML coloreadas del resumen (ver _RESUMEN_COLORES) —
    separado de la tarjeta que las envuelve para poder reusarlas tanto en la
    vista normal como en el componente con botón de copiar (mismo HTML en
    los dos lados, para que "lo que se ve" y "lo que se copia" sean lo mismo)."""
    filas = []
    for linea in texto.split("\n"):
        if not linea:
            filas.append('<div style="height:6px"></div>')
        elif linea[0] in ("✅", "❌", "➖"):
            cls = {"✅": "ok", "❌": "err", "➖": "na"}[linea[0]]
            color_txt = _RESUMEN_COLORES[cls]
            # Sin display:flex: al pegar en ADO, un div flex con spans
            # sueltos se desarma y el ícono queda en su propia línea.
            filas.append(
                f'<div style="font-size:12.5px;line-height:1.5;padding:2px 0;color:{color_txt}">'
                f'{linea[0]} {html.escape(linea[1:].strip())}</div>'
            )
        elif linea.startswith("HU "):
            filas.append(f'<div style="font-weight:800;font-size:13.5px;color:#2C2A29">{html.escape(linea)}</div>')
        elif linea.startswith("Estado de Flujo:"):
            # Lo primero que hay que ver al abrir el resumen — se destaca más
            # que el resto (más grande, en negrita, coloreado según el estado).
            _valor = linea.split(":", 1)[1].strip()
            _color_estado = {"LISTO": "#065F46", "CON ERRORES": "#991B1B"}.get(_valor, "#92400E")
            filas.append(
                f'<div style="font-size:14.5px;font-weight:800;margin:2px 0 4px;color:{_color_estado}">'
                f'Estado de Flujo: {html.escape(_valor)}</div>'
            )
        elif linea.startswith("🔗"):
            # Datos técnicos de referencia (solo aparecen en PDN).
            filas.append(
                f'<div style="font-size:12px;color:#1D4ED8;font-family:ui-monospace,SFMono-Regular,'
                f'Menlo,Consolas,monospace;word-break:break-all;margin-bottom:3px">{html.escape(linea)}</div>'
            )
        else:
            filas.append(f'<div style="font-size:12px;color:#78716C;margin-bottom:4px">{html.escape(linea)}</div>')
    return "".join(filas)


def _render_resumen_copiable(texto: str):
    """Misma tarjeta coloreada de siempre, pero con un botón "Copiar" que usa
    el portapapeles del navegador (Clipboard API) para copiar tanto el HTML
    con formato y colores (para pegar en el campo Resolution de ADO, que es
    texto enriquecido) como el texto plano (para cualquier otro destino) —
    sin necesidad de un bloque de texto aparte ni de seleccionar a mano.

    Va en un iframe (st.iframe con HTML crudo, no una URL) porque un
    <script> dentro de st.markdown no se ejecuta — es la única forma de
    correr JS real en Streamlit. height="content" (auto) no reajusta bien
    cuando el contenido cambia de tamaño entre renders (deja un espacio en
    blanco enorme si el resumen se acorta) — se calcula el alto a mano según
    la cantidad de líneas, como antes."""
    filas_html = _resumen_filas_html(texto)
    _n_lineas = texto.count("\n") + 1
    _altura = 60 + _n_lineas * 21

    _html_para_portapapeles = f'<div style="font-family:-apple-system,Segoe UI,sans-serif">{filas_html}</div>'
    _html_js = json.dumps(_html_para_portapapeles)
    _texto_js = json.dumps(texto)

    st.iframe(f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;position:relative">
        <button id="btn-copiar-resumen" style="position:absolute;top:10px;right:10px;z-index:1;
            background:#2C2A29;color:#fff;border:none;border-radius:6px;padding:5px 12px;
            font-size:11.5px;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:5px">
            <span id="icono-copiar">⧉</span><span id="texto-copiar">Copiar</span>
        </button>
        <div style="background:#F5F5F4;border:1px solid #E7E5E4;border-radius:10px;padding:12px 16px;padding-right:90px">
            {filas_html}
        </div>
    </div>
    <script>
        const boton = document.getElementById("btn-copiar-resumen");
        boton.addEventListener("click", async () => {{
            const html = {_html_js};
            const texto = {_texto_js};
            try {{
                await navigator.clipboard.write([
                    new ClipboardItem({{
                        "text/html": new Blob([html], {{type: "text/html"}}),
                        "text/plain": new Blob([texto], {{type: "text/plain"}}),
                    }})
                ]);
            }} catch (e) {{
                // Navegadores que no soportan ClipboardItem con varios tipos
                // (o sin permiso de portapapeles) — al menos el texto plano.
                await navigator.clipboard.writeText(texto);
            }}
            document.getElementById("texto-copiar").innerText = "Copiado";
            document.getElementById("icono-copiar").innerText = "✓";
            setTimeout(() => {{
                document.getElementById("texto-copiar").innerText = "Copiar";
                document.getElementById("icono-copiar").innerText = "⧉";
            }}, 1800);
        }});
    </script>
    """, height=_altura)


def render_hu_detail(resultados, sprint_activo):
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
        _title = r.get('hu_title', '')  # sin recortar: la búsqueda del selectbox necesita el título completo
        _tipo  = r.get('tipo_cambio', '')[:4]
        _icon  = ESTADO_ICON.get(get_estado_code(r), ICON_WARNING)
        return f"{_icon} {_id} — {_title} [{_tipo}]"

    if not resultados:
        st.warning("No hay HU para mostrar con los filtros seleccionados")
        st.stop()

    # Mismo filtro que la tabla del backlog (buscar + validación) — para
    # ubicar rápido una HU puntual sin tener que scrollear el selectbox
    # entero cuando el sprint tiene muchas.
    col_busca_hu, col_val_hu = st.columns([0.65, 0.35])
    with col_busca_hu:
        _texto_busqueda_hu = st.text_input(
            "Buscar HU", placeholder="Buscar por ID o palabra del título...",
            label_visibility="collapsed", key="hu_detail_busqueda", icon=MI_SEARCH,
        )
    with col_val_hu:
        _filtro_validacion_hu = st.selectbox(
            "Validación", ["Todas", "Listo", "Con errores", "Incompleto"],
            label_visibility="collapsed", key="hu_detail_filtro_validacion",
        )

    _resultados_filtrados = resultados
    if _texto_busqueda_hu.strip():
        _q = _texto_busqueda_hu.strip().lower()
        _resultados_filtrados = [
            r for r in _resultados_filtrados
            if _q in str(r.get("hu_id", "")).lower() or _q in r.get("hu_title", "").lower()
        ]
    if _filtro_validacion_hu != "Todas":
        _mapa_validacion_hu = {"Listo": ESTADO_LISTO, "Con errores": ESTADO_ERROR}
        if _filtro_validacion_hu in _mapa_validacion_hu:
            _resultados_filtrados = [r for r in _resultados_filtrados if get_estado_code(r) == _mapa_validacion_hu[_filtro_validacion_hu]]
        else:  # "Incompleto" = todo lo que no es ni Listo ni Con errores
            _resultados_filtrados = [r for r in _resultados_filtrados if get_estado_code(r) not in (ESTADO_LISTO, ESTADO_ERROR)]

    if not _resultados_filtrados:
        st.info("Ninguna HU coincide con estos filtros.", icon=MI_INFO)
        st.stop()

    # El selectbox persiste el hu_id como valor, no el label armado (que
    # trae un ícono de estado que puede cambiar al re-analizar) — si
    # persistiera el label, un cambio de ícono deja la opción anterior fuera
    # de la lista nueva y Streamlit vuelve en silencio a la primera HU.
    hu_por_id = {r.get("hu_id"): r for r in _resultados_filtrados}

    # Red de seguridad extra ante el caso reportado de que la selección
    # salta a la primera HU tras ciertas acciones (guardar credenciales AWS,
    # subir un componente): se guarda la elección en "_hu_select_shadow" y
    # se restaura acá si "hu_select" no está o apunta a una HU que ya no existe.
    _shadow = st.session_state.get("_hu_select_shadow")
    if _shadow in hu_por_id and st.session_state.get("hu_select") not in hu_por_id:
        st.session_state["hu_select"] = _shadow

    seleccion_id = st.selectbox(
        "Selecciona una HU para ver detalles",
        list(hu_por_id.keys()),
        format_func=lambda hid: _hu_label(hu_por_id[hid]),
        key="hu_select",
    )
    st.session_state["_hu_select_shadow"] = seleccion_id

    if seleccion_id is not None:
        r   = hu_por_id[seleccion_id]
        val = r.get("validaciones", {})
        # La consola "Subir a AWS" (más abajo) usa esto para saber a qué HU referirse.
        st.session_state["hu_activa_id"] = r.get("hu_id")

        sprint_path = Path(ROOT_FOLDER) / sprint_activo
        hu_folder = None
        hu_id_str = str(r.get("hu_id", ""))

        if sprint_path.exists():
            for d in sprint_path.iterdir():
                if not d.is_dir():
                    continue
                # "-" al final es obligatorio: sin esto, HU "100" matcheaba
                # por error la carpeta "1002-..." (prefijo numérico de otro ID).
                if d.name.startswith(f"{hu_id_str}-"):
                    hu_folder = d
                    break

        _ta_files  = r.get("ta_files", [])
        _aid_files = r.get("aid_files", [])
        _udz_files = r.get("udz_files", [])
        if hu_folder and (len(_ta_files) > 1 or len(_aid_files) > 1 or len(_udz_files) > 1):
            st.markdown(
                f"<div class='step-card-help'>{ICON_WARNING} Esta HU trae varios archivos TA, AID y/o UDZ en adjuntos — elegí cuál usar para el análisis</div>",
                unsafe_allow_html=True,
            )
            _estado_code_sel = get_estado_code(r)
            if _estado_code_sel == ESTADO_LISTO:
                _sel_icon, _sel_color = ICON_OK, "#15803D"
            elif _estado_code_sel == ESTADO_ERROR:
                _sel_icon, _sel_color = ICON_ERROR, "#B91C1C"
            else:
                _sel_icon, _sel_color = ICON_WARNING, "#B45309"

            def _label_coloreado(texto):
                st.markdown(
                    f"<div style='font-size:13px;font-weight:600;color:{_sel_color};margin-bottom:2px'>{_sel_icon} {texto}</div>",
                    unsafe_allow_html=True,
                )

            col_pick_ta, col_pick_aid, col_pick_udz = st.columns(3)
            _ta_override = None
            _aid_override = None
            _udz_override = None
            if len(_ta_files) > 1:
                with col_pick_ta:
                    _label_coloreado("TA a usar")
                    _ta_names = [Path(p).name for p in _ta_files]
                    _ta_activo_name = Path(r.get("ta_activo") or _ta_files[0]).name
                    _ta_sel = st.selectbox(
                        "TA a usar", _ta_names,
                        index=_ta_names.index(_ta_activo_name) if _ta_activo_name in _ta_names else 0,
                        key=f"ta_pick_{hu_id_str}",
                        label_visibility="collapsed",
                    )
                    _ta_override = Path([p for p in _ta_files if Path(p).name == _ta_sel][0])
            if len(_aid_files) > 1:
                with col_pick_aid:
                    _label_coloreado("AID a usar")
                    _aid_names = [Path(p).name for p in _aid_files]
                    _aid_activo_name = Path(r.get("aid_activo") or _aid_files[0]).name
                    _aid_sel = st.selectbox(
                        "AID a usar", _aid_names,
                        index=_aid_names.index(_aid_activo_name) if _aid_activo_name in _aid_names else 0,
                        key=f"aid_pick_{hu_id_str}",
                        label_visibility="collapsed",
                    )
                    _aid_override = Path([p for p in _aid_files if Path(p).name == _aid_sel][0])
            if len(_udz_files) > 1:
                with col_pick_udz:
                    _label_coloreado("UDZ a usar")
                    _udz_names = [Path(p).name for p in _udz_files]
                    _udz_activo_name = Path(r.get("udz_activo") or _udz_files[0]).name
                    _udz_sel = st.selectbox(
                        "UDZ a usar", _udz_names,
                        index=_udz_names.index(_udz_activo_name) if _udz_activo_name in _udz_names else 0,
                        key=f"udz_pick_{hu_id_str}",
                        label_visibility="collapsed",
                    )
                    _udz_override = Path([p for p in _udz_files if Path(p).name == _udz_sel][0])

            _ta_cambio = _ta_override and Path(r.get("ta_activo") or "") != _ta_override
            _aid_cambio = _aid_override and Path(r.get("aid_activo") or "") != _aid_override
            _udz_cambio = _udz_override and Path(r.get("udz_activo") or "") != _udz_override
            if _ta_cambio or _aid_cambio or _udz_cambio:
                nuevo = analizar_hu(hu_folder, ta_override=_ta_override, aid_override=_aid_override, udz_override=_udz_override)
                _res = st.session_state.get("resultados", [])
                for _i, _x in enumerate(_res):
                    if str(_x.get("hu_id")) == hu_id_str:
                        _res[_i] = nuevo
                        break
                st.session_state["resultados"] = _res
                st.rerun()

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

        # Ambiente y Estado son lo primero que hay que mirar de un vistazo,
        # por eso van coloreados — pero como chips del mismo tamaño que el
        # resto (no una insignia aparte y gigante), para que se lea como una
        # sola fila prolija, no como dos estilos distintos peleando entre sí.
        _amb_colores = {
            "PDN": ("#FEE2E2", "#B91C1C", "#FCA5A5"),
            "QA":  ("#FEF3C7", "#92400E", "#FDE68A"),
        }
        _amb_bg, _amb_txt, _amb_border = _amb_colores.get(amb_h.upper(), ("#F5F5F4", "#57534E", "#E7E5E4"))

        _estado_code_h = get_estado_code(r)
        _estado_colores = {
            ESTADO_LISTO: ("#D1FAE5", "#065F46", "#6EE7B7"),
            ESTADO_ERROR: ("#FEE2E2", "#991B1B", "#FCA5A5"),
        }
        _est_bg, _est_txt, _est_border = _estado_colores.get(_estado_code_h, ("#FEF3C7", "#92400E", "#FDE68A"))

        col_header, col_refresh = st.columns([0.85, 0.15], vertical_alignment="center")
        with col_header:
            st.markdown(f"""
            <div class="hu-detail-header">
                <div style="width:100%">
                    <div class="hu-detail-id">HU {r.get('hu_id')} · {tipo_h}</div>
                    <div class="hu-detail-title">{r.get('hu_title','')}</div>
                    <div class="hu-detail-chips">
                        <span class="hu-chip" style="background:{_amb_bg};color:{_amb_txt};border-color:{_amb_border};font-weight:800">Ambiente {amb_h}</span>
                        <span class="hu-chip" style="background:{_est_bg};color:{_est_txt};border-color:{_est_border};font-weight:800">{r.get('estado_general','')}</span>
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

        # Único paso de confirmación manual antes del despliegue — no hay
        # "aprobado" separado, el mismo usuario que ejecuta el flujo confirma.
        _analizado_por     = r.get("analizado_por")
        _analizado_en_fmt  = r.get("analizado_en", "")[:16].replace("T", " ")
        _qa_por            = r.get("probado_qa_por")
        _qa_en_fmt         = r.get("probado_qa_en", "")[:16].replace("T", " ")
        _qa_estado         = r.get("probado_qa_estado_code")
        _estado_code_hoy   = get_estado_code(r)

        if _analizado_por:
            st.caption(f"Último análisis: {_analizado_por} — {_analizado_en_fmt}")

        _qa_vigente = bool(_qa_por) and _qa_estado == _estado_code_hoy == ESTADO_LISTO

        if _qa_por and not _qa_vigente:
            st.warning(
                f"Se probó en QA por {_qa_por} el {_qa_en_fmt}, pero el análisis cambió desde entonces — revisar antes de confiar en esta prueba",
                icon=MI_WARNING,
            )

        if _qa_vigente:
            st.success(f"Probado en QA por {_qa_por} — {_qa_en_fmt}", icon=MI_APPROVE)
        else:
            # Opcional: no todas las HU pasan por una prueba en QA antes de
            # PDN — por eso nunca bloquea el despliegue, solo deja constancia
            # de que alguien la probó, para quien lo necesite.
            _puede_marcar_qa = _estado_code_hoy == ESTADO_LISTO
            if st.button("Marcar como probado en QA (opcional)", key=f"qa_{r.get('hu_id')}", width='stretch',
                         icon=MI_APPROVE, disabled=not _puede_marcar_qa,
                         help=None if _puede_marcar_qa else "Solo se puede marcar si el estado actual es LISTO"):
                if hu_folder:
                    _ahora = datetime.now().isoformat()
                    _usuario = obtener_usuario_actual()
                    r["probado_qa_por"] = _usuario
                    r["probado_qa_en"] = _ahora
                    r["probado_qa_estado_code"] = _estado_code_hoy
                    out_path = hu_folder / "analisis" / "analisis_tecnico.json"
                    out_path.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
                    _res = st.session_state.get("resultados", [])
                    for _i, _x in enumerate(_res):
                        if str(_x.get("hu_id")) == str(r.get("hu_id")):
                            _res[_i] = r
                            break
                    st.session_state["resultados"] = _res
                    # st.toast (no st.success): el rerun de abajo borra mensajes inline.
                    st.toast("QA registrado", icon=MI_OK)
                    st.rerun()

        # "Desplegado en PDN" ya no es un checkbox que cualquiera marca: se
        # calcula solo, mirando si TA/AID/UDZ realmente se subieron con éxito
        # a la tabla de PDN (consola "Subir a AWS", más abajo) — ver
        # core.analysis.obtener_estado_pdn_real.
        _pdn_real = obtener_estado_pdn_real(r)
        if _pdn_real["desplegado"]:
            _pdn_en_fmt = (_pdn_real["en"] or "")[:16].replace("T", " ")
            st.success(f"Desplegado en PDN — confirmado por subida real a AWS · {_pdn_real['por']} — {_pdn_en_fmt}", icon=MI_APPROVE)
        else:
            st.info(
                "Todavía no está desplegado en PDN — se marca solo cuando TA/AID/UDZ se suban con éxito "
                "al ambiente PDN en la consola 'Subir a AWS' (más abajo).",
                icon=MI_INFO,
            )

        _texto_resumen, _completo_resumen = _generar_resumen_resolution(r)

        with st.expander("Resumen para Resolution de ADO", expanded=False, icon=MI_OK if _completo_resumen else MI_SUMMARY):
            _render_resumen_copiable(_texto_resumen)

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

        if rnf_path:
            _rnf_copiado_por = r.get("rnf_copiado_por")
            if _rnf_copiado_por:
                _rnf_copiado_en_fmt = (r.get("rnf_copiado_en") or "")[:16].replace("T", " ")
                st.caption(f"{ICON_OK} RNF copiado al acumulado por {_rnf_copiado_por} — {_rnf_copiado_en_fmt}")
            else:
                if st.button("Marcar RNF copiado al acumulado", key=f"btn_rnf_copiado_{r.get('hu_id')}",
                             icon=MI_OK, help="Confirmá esto después de pasar los datos del RNF al Excel acumulado del área"):
                    if hu_folder:
                        r["rnf_copiado_por"] = obtener_usuario_actual()
                        r["rnf_copiado_en"] = datetime.now().isoformat()
                        out_path = hu_folder / "analisis" / "analisis_tecnico.json"
                        out_path.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
                        _res = st.session_state.get("resultados", [])
                        for _i, _x in enumerate(_res):
                            if str(_x.get("hu_id")) == str(r.get("hu_id")):
                                _res[_i] = r
                                break
                        st.session_state["resultados"] = _res
                        st.toast("RNF marcado como copiado", icon=MI_OK)
                        st.rerun()

        st.divider()

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

        with st.expander("GUÍA: Cómo Analizar Esta HU", expanded=False, icon=MI_GUIDE):
            guia = mostrar_guia_tipo(r.get("tipo_cambio", "DESPLIEGUE"))
            st.markdown(guia)

        st.divider()

        _arcs    = r.get("archivos", {})
        _f_ta    = _arcs.get("TA",  "TA")
        _f_aid   = _arcs.get("AID", "AID")
        _f_udz   = _arcs.get("UDZ", "UDZ")

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

        # Misma lista canónica de claves que usa analizar_hu, así no se desincroniza de estado_code.
        n_na  = sum(1 for k in VALIDATION_KEYS if val.get(k, {}).get("na", False))
        n_ok  = sum(1 for k in VALIDATION_KEYS if not val.get(k, {}).get("na", False) and _val_ok(val.get(k, {})))
        n_err = len(VALIDATION_KEYS) - n_na - n_ok

        _parts = []
        if n_ok:  _parts.append(f"{ICON_OK} {n_ok} correctas")
        if n_err: _parts.append(f"{ICON_ERROR} {n_err} con error")
        if n_na:  _parts.append(f"{ICON_NA} {n_na} no aplican")
        _exp_label = "Validaciones críticas — " + ("  ·  ".join(_parts) if _parts else "sin datos")

        with st.expander(_exp_label, expanded=True):
            # Qué archivo exacto se está evaluando — clave cuando hay varios TA/AID/UDZ.
            _archivos_vista = []
            for _clave, _color_v in (("TA", "#0369A1"), ("AID", "#7C3AED"), ("UDZ", "#065F46")):
                _val_arc = arcs_h.get(_clave, "")
                if "NO" not in _val_arc:
                    _archivos_vista.append(
                        f"<span style='display:inline-flex;align-items:center;gap:4px;background:#fff;"
                        f"border:1.5px solid {_color_v};border-radius:6px;padding:3px 9px;font-size:11.5px;"
                        f"font-weight:700;color:{_color_v}'>{_clave} <code style='background:none;color:{_color_v};"
                        f"font-weight:600;padding:0'>{_val_arc}</code></span>"
                    )
            if _archivos_vista:
                st.markdown(
                    "<div style='margin-bottom:10px'><span style='font-size:11px;font-weight:700;color:#78716C;"
                    "margin-right:6px'>ESTÁS VIENDO:</span>" + " ".join(_archivos_vista) + "</div>",
                    unsafe_allow_html=True,
                )

            _col_desc, _col_refresh_val = st.columns([0.82, 0.18], vertical_alignment="center")
            with _col_desc:
                st.markdown(
                    "Verifica la conexión entre **TA** (Text Analyzer — extracción), **AID** (configuración) y **UDZ** (eventos). "
                    "Los tres deben estar alineados para que el flujo funcione en producción."
                )
            with _col_refresh_val:
                # Repetido acá para no tener que subir hasta el header a cada rato.
                if st.button("Actualizar", key=f"refresh_val_{r.get('hu_id')}", icon=MI_REFRESH, width='stretch',
                             help="Relee los JSON y recalcula validaciones"):
                    if hu_folder:
                        nuevo = analizar_hu(hu_folder)
                        _res = st.session_state.get("resultados", [])
                        for _i, _x in enumerate(_res):
                            if str(_x.get("hu_id")) == str(r.get("hu_id")):
                                _res[_i] = nuevo
                                break
                        st.session_state["resultados"] = _res
                        st.rerun()

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
            _s3_tipo_udz = s3_info.get("tipo_udz", "DESCONOCIDO")
            _s3_esperado = s3_info.get("esperado", "")
            _s3_es_resultados = _s3_tipo_udz == "RESULTADOS"
            def _s3_detail():
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**AID s3_path encontrado:**")
                    st.code(aid_path or "(vacío)", language="text")
                with col2:
                    st.markdown("**UDZ s3_path encontrado:**")
                    st.code(udz_path or "(vacío)", language="text")
                if _s3_es_resultados:
                    st.markdown("**Regla:** UDZ es de **transmisión (salida) — RESULTADOS**: la ruta no es idéntica a la de AID a propósito — donde AID dice `crudos`, UDZ debe decir `resultados` (el resto de la ruta igual)")
                else:
                    st.markdown("**Regla:** UDZ es de **crudos (entrada)**: la ruta debe coincidir exactamente con la de AID (se ignora `/` al final)")
                if aid_path and udz_path and normalizar_s3(udz_path) != _s3_esperado:
                    st.error(f"{ICON_ERROR} **Mismatch detectado** — Alinear UDZ a:")
                    st.info(f'**En UDZ** → `Ctrl+F: s3_path`\n```json\n"s3_path": "{_s3_esperado}"\n```')
            val_card(s3_ok, "S3 Path — AID = UDZ", f"{_f_aid} & {_f_udz}",
                     "Crudos: ruta idéntica a AID · Resultados: igual pero con 'crudos'→'resultados'", _s3_detail,
                     na=s3_na, campo="AID.s3_path ↔ UDZ.item.s3_path", valor_ok=_s3_esperado if _s3_esperado else None)

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
