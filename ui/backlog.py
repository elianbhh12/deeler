"""Tarjeta del Excel consolidado y la tabla resumen de HU del sprint."""
import os
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

from core.config import ROOT_FOLDER, ICON_OK, ICON_ERROR, ICON_WARNING, ICON_NA, ESTADO_LISTO, ESTADO_ERROR, MI_FOLDER, MI_ERROR, MI_SEARCH, MI_INFO
from core.analysis import get_estado_code, obtener_estado_pdn_real


def render_excel_card():
    #  Excel consolidado — tarjeta siempre visible
    _excel_file  = Path(ROOT_FOLDER) / "Consolidado_Backlog.xlsx"
    _excel_ok    = _excel_file.exists()
    _excel_mtime = datetime.fromtimestamp(_excel_file.stat().st_mtime).strftime("%d/%m/%Y %H:%M") if _excel_ok else None
    _excel_size  = f"{_excel_file.stat().st_size / 1024:.0f} KB" if _excel_ok else None

    _status_color  = "#D1FAE5" if _excel_ok else "#FEF3C7"
    _status_border = "#00C389" if _excel_ok else "#F59E0B"
    _status_icon   = ICON_OK if _excel_ok else ICON_WARNING
    _status_txt    = f"Actualizado {_excel_mtime} — {_excel_size}" if _excel_ok else "Aún no generado — analiza el sprint primero"

    # Card + botón en la misma fila con columnas, centrados verticalmente entre sí
    _col_card, _col_btn = st.columns([0.82, 0.18], vertical_alignment="center")
    with _col_card:
        st.markdown(f"""
        <div style="background:{_status_color};border:1px solid {_status_border};border-radius:10px;
                    padding:10px 14px;display:flex;align-items:center;gap:10px;min-height:42px;box-sizing:border-box">
            <div>
                <div style="font-weight:700;font-size:12px;color:#2C2A29">Consolidado Excel del backlog</div>
                <div style="font-size:11px;color:#78716C;margin-top:1px">{_status_icon} {_status_txt}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with _col_btn:
        if _excel_ok:
            if st.button("Abrir", key="btn_open_excel", width='stretch', icon=MI_FOLDER,
                         help="Abrir Consolidado_Backlog.xlsx", type="primary"):
                try:
                    # os.startfile abre directo con la app asociada (Excel) —
                    # subprocess con 'start'/shell=True a veces abre la
                    # ventana de CMD en su lugar, según cómo esté configurado
                    # el equipo (visto en PC de la empresa).
                    os.startfile(str(_excel_file))
                except Exception as ex:
                    st.error(f"No se pudo abrir: {ex}", icon=MI_ERROR)
        else:
            st.button("Abrir", key="btn_open_excel", width='stretch', icon=MI_FOLDER, disabled=True)

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)


def render_tabla_resumen(resultados):
    #  Filtros — con pocas HU no hacía falta, pero apenas crece el sprint (o
    #  se quiere ubicar una HU puntual) no había forma de acotar la tabla más
    #  que scrolleando a ojo.
    col_busca, col_val = st.columns([0.65, 0.35])
    with col_busca:
        texto_busqueda = st.text_input(
            "Buscar", placeholder="Buscar por ID o palabra del título...",
            label_visibility="collapsed", key="backlog_busqueda", icon=MI_SEARCH,
        )
    with col_val:
        filtro_validacion = st.selectbox(
            "Validación", ["Todas", "Listo", "Con errores", "Incompleto"],
            label_visibility="collapsed", key="backlog_filtro_validacion",
        )

    filtered_resultados = resultados

    if texto_busqueda.strip():
        _q = texto_busqueda.strip().lower()
        filtered_resultados = [
            r for r in filtered_resultados
            if _q in str(r.get("hu_id", "")).lower() or _q in r.get("hu_title", "").lower()
        ]

    if filtro_validacion != "Todas":
        _mapa_validacion = {"Listo": ESTADO_LISTO, "Con errores": ESTADO_ERROR}
        if filtro_validacion in _mapa_validacion:
            filtered_resultados = [r for r in filtered_resultados if get_estado_code(r) == _mapa_validacion[filtro_validacion]]
        else:  # "Incompleto" = todo lo que no es ni Listo ni Con errores (INCOMPLETO/SIN_METADATA)
            filtered_resultados = [r for r in filtered_resultados if get_estado_code(r) not in (ESTADO_LISTO, ESTADO_ERROR)]

    if not filtered_resultados:
        st.info("Ninguna HU coincide con estos filtros.", icon=MI_INFO)
        return

    # Crear tabla como DataFrame simple
    tabla_data = []
    #  ORDENAR POR FECHA DE DESCARGA (MÁS RECIENTES PRIMERO)
    filtered_resultados_ordenados = sorted(
        filtered_resultados,
        key=lambda x: x.get("downloaded_at", ""),
        reverse=True
    )

    for r in filtered_resultados_ordenados:
        val   = r.get("validaciones", {})
        arcs  = r.get("archivos", {})
        tipo_r = r.get("tipo_cambio", "").upper()
        es_desp = "DESPLIEGUE" in tipo_r

        def _arc_badge(key):
            val_arc = arcs.get(key, "")
            if "NO" not in val_arc:
                return ICON_OK
            return ICON_ERROR if es_desp else ICON_NA  # N/A = no aplica en modificación

        ta_ok  = _arc_badge("TA")
        aid_ok = _arc_badge("AID")
        udz_ok = _arc_badge("UDZ")
        rnf_ok = ICON_OK if "NO" not in arcs.get("RNF", "") else ICON_ERROR

        #  Desplegado en PDN — se infiere de subidas reales a AWS (TA/AID/UDZ
        #  ya en la tabla PDN), no de un checkbox manual. Ver
        #  core.analysis.obtener_estado_pdn_real.
        _pdn_real = obtener_estado_pdn_real(r)
        if _pdn_real["desplegado"]:
            desplegado_badge = f"{ICON_OK} {(_pdn_real['en'] or '')[:10]}"
        else:
            desplegado_badge = ICON_NA

        # Agregar fecha descarga para referencia
        downloaded_at = r.get("downloaded_at", "")
        fecha_str = f"{downloaded_at[:10]} {downloaded_at[11:19]}" if downloaded_at else "?"

        _est_code = get_estado_code(r)
        _est_short = f"{ICON_OK} Listo" if _est_code == ESTADO_LISTO else (f"{ICON_ERROR} Errores" if _est_code == ESTADO_ERROR else f"{ICON_WARNING} Incompleto")
        tabla_data.append({
            "ID": r.get('hu_id','?'),
            "Título": r.get('hu_title','?'),
            "Tipo": r.get('tipo_cambio', '?'),
            "RNF": rnf_ok,
            "TA": ta_ok,
            "AID": aid_ok,
            "UDZ": udz_ok,
            # "Validación" = pasó las 12 validaciones críticas; distinto de
            # "Desplegado PDN" = la HU ya terminó de verdad (subió a PDN).
            # Una HU puede estar en Validación=Listo y aun así seguir
            # pendiente hasta que se despliegue.
            "Validación": _est_short,
            "Desplegado PDN": desplegado_badge,
        })

    if tabla_data:
        df_tabla = pd.DataFrame(tabla_data)
        df_tabla["ID"] = df_tabla["ID"].astype(str).str.replace(",", "", regex=False)

        def _color_celda(val):
            texto = str(val)
            if ICON_OK in texto:
                return "background-color:#D1FAE5;color:#065F46"
            if ICON_ERROR in texto:
                return "background-color:#FEE2E2;color:#991B1B"
            if ICON_WARNING in texto:
                return "background-color:#FEF3C7;color:#92400E"
            if ICON_NA in texto:
                return "background-color:#F5F5F4;color:#78716C"
            return ""

        _estilo = df_tabla.style.map(_color_celda, subset=["RNF", "TA", "AID", "UDZ", "Validación", "Desplegado PDN"])
        st.dataframe(
            _estilo, width='stretch', hide_index=True,
            column_config={"Título": st.column_config.TextColumn("Título", width="large")},
        )

        #  Alertas de RNF faltante
        sin_rnf = [r.get('hu_id') for r in filtered_resultados if not r.get('rnf_path')]
        if sin_rnf:
            st.warning(
                f"{ICON_WARNING} **{len(sin_rnf)} HU sin RNF** — Revísalas en detalle y valida si tienen el Excel:\n\n" +
                ", ".join(f"`{hid}`" for hid in sin_rnf)
            )

    st.markdown("")
