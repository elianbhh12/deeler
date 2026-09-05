"""Carga de resultados en sesión y KPIs + barra de progreso del sprint."""
from pathlib import Path

import streamlit as st

from core.config import ROOT_FOLDER, ESTADO_LISTO, ESTADO_ERROR, ESTADO_INCOMPLETO, ESTADO_SIN_METADATA
from core.analysis import cargar_json, get_estado_code, obtener_estado_pdn_real
from core.reports import generar_excel_consolidado


def cargar_resultados():
    """Trae los resultados de la sesión (o del disco si no están en memoria).

    Si no hay nada que mostrar, renderiza el estado vacío y detiene el script
    (st.stop() corta acá el resto del render, como hacía el código original).
    """
    resultados    = st.session_state.get("resultados", [])
    sprint_activo = st.session_state.get("sprint_activo", "")

    # Cargar análisis existente si hay sprint seleccionado
    if not resultados and sprint_activo:
        sprint_path = Path(ROOT_FOLDER) / sprint_activo
        if sprint_path.exists():
            cargados = []
            for d in sorted(sprint_path.iterdir()):
                if not d.is_dir():
                    continue
                an = d / "analisis" / "analisis_tecnico.json"
                if an.exists():
                    cargados.append(cargar_json(an))
            if cargados:
                resultados = cargados
                st.session_state["resultados"] = resultados

    if not resultados:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-state-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l2-5h14l2 5"/><path d="M3 9v9a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1V9"/><path d="M3 9h5.5l1 3h5l1-3H21"/></svg></div>
            <div class="empty-state-title">Sin datos cargados</div>
            <div class="empty-state-sub">
                Selecciona un sprint en <b>Paso 1</b>, descárgalo,<br>
                luego elige el sprint en <b>Paso 2</b> y haz clic en <b>Analizar sprint</b>.
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    return resultados, sprint_activo


def render_kpis_y_progreso(resultados):
    #  Métricas — la HU termina cuando se despliega en PDN, no cuando pasa
    #  las validaciones: "Listos" (validación ok) se separa de "Desplegados"
    #  (ya en PDN de verdad). "Pendientes" es lo que queda por cerrar: HU
    #  validadas sin errores que todavía no llegaron a PDN.
    total       = len(resultados)
    listos      = sum(1 for r in resultados if get_estado_code(r) == ESTADO_LISTO)
    desplegados = sum(1 for r in resultados if obtener_estado_pdn_real(r)["desplegado"])
    pendientes  = max(0, listos - desplegados)
    errores     = sum(1 for r in resultados if get_estado_code(r) == ESTADO_ERROR)
    sin_arch    = sum(1 for r in resultados if get_estado_code(r) in (ESTADO_INCOMPLETO, ESTADO_SIN_METADATA))
    errores_total = errores + sin_arch

    #  GUARDAR EXCEL — solo si el sprint fue recién analizado
    backlog_folder = Path("Backlog_Dealer")
    if st.session_state.get("_excel_pending"):
        try:
            generar_excel_consolidado(resultados, guardar_en_carpeta=backlog_folder)
        except Exception:
            pass
        st.session_state["_excel_pending"] = False

    col1, col2, col3, col4 = st.columns(4, gap="medium")

    with col1:
        st.markdown(f"""
        <div class="spyra-kpi spyra-border-dark">
            <div class="spyra-kpi-label">HU Totales</div>
            <div class="spyra-kpi-value">{total}</div>
            <div class="spyra-kpi-sub">Historias analizadas</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="spyra-kpi spyra-border-green">
            <div class="spyra-kpi-label">Desplegados en PDN</div>
            <div class="spyra-kpi-value">{desplegados}</div>
            <div class="spyra-kpi-sub">Flujo terminado end-to-end</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div class="spyra-kpi spyra-border-orange">
            <div class="spyra-kpi-label">Errores</div>
            <div class="spyra-kpi-value">{errores_total}</div>
            <div class="spyra-kpi-sub">Requieren corrección</div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown(f"""
        <div class="spyra-kpi spyra-border-purple">
            <div class="spyra-kpi-label">Pendientes</div>
            <div class="spyra-kpi-value">{pendientes}</div>
            <div class="spyra-kpi-sub">Listas, falta desplegar a PDN</div>
        </div>
        """, unsafe_allow_html=True)

    #  RESUMEN EJECUTIVO + PROGRESO — la HU termina cuando llega a PDN, así
    #  que el % principal es el de despliegue real, no solo el de validación.
    pct_desp = round((desplegados   / total) * 100) if total else 0
    pct_pend = round((pendientes    / total) * 100) if total else 0
    pct_err  = round((errores_total / total) * 100) if total else 0

    # Color del círculo/número principal
    _pct_color = "#00C389" if pct_desp == 100 else ("#E53C3C" if errores_total > 0 else "#FDDA24")

    st.markdown(f"""
    <div style="background:white;border:1px solid #E7E5E4;border-radius:16px;padding:20px 28px;
                box-shadow:0 2px 8px rgba(0,0,0,.05);margin-top:16px;margin-bottom:12px">

      <!-- Fila superior: título + porcentaje grande -->
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
        <div>
          <div style="font-size:13px;font-weight:700;color:#78716C;letter-spacing:.04em;text-transform:uppercase">
            Progreso del sprint
          </div>
          <div style="font-size:22px;font-weight:800;color:#2C2A29;margin-top:2px">
            {desplegados} de {total} HU desplegadas en PDN
          </div>
        </div>
        <div style="font-size:42px;font-weight:900;color:{_pct_color};line-height:1">
          {pct_desp}<span style="font-size:20px;font-weight:700">%</span>
        </div>
      </div>

      <!-- Barra segmentada -->
      <div style="width:100%;height:14px;background:#F5F5F4;border-radius:999px;overflow:hidden;display:flex;margin-bottom:14px">
        <div style="width:{pct_desp}%;background:#00C389;transition:width .4s ease" title="Desplegados {pct_desp}%"></div>
        <div style="width:{pct_pend}%;background:#FDDA24;transition:width .4s ease" title="Pendientes {pct_pend}%"></div>
        <div style="width:{pct_err}%;background:#E53C3C;transition:width .4s ease" title="Errores {pct_err}%"></div>
      </div>

      <!-- Leyenda -->
      <div style="display:flex;gap:20px;flex-wrap:wrap">
        <div style="display:flex;align-items:center;gap:6px;font-size:12px;color:#44403C;font-weight:600">
          <div style="width:10px;height:10px;border-radius:50%;background:#00C389"></div>
          Desplegados &nbsp;<b style="color:#00C389">{desplegados} ({pct_desp}%)</b>
        </div>
        <div style="display:flex;align-items:center;gap:6px;font-size:12px;color:#44403C;font-weight:600">
          <div style="width:10px;height:10px;border-radius:50%;background:#FDDA24"></div>
          Pendientes &nbsp;<b style="color:#B45309">{pendientes} ({pct_pend}%)</b>
        </div>
        <div style="display:flex;align-items:center;gap:6px;font-size:12px;color:#44403C;font-weight:600">
          <div style="width:10px;height:10px;border-radius:50%;background:#E53C3C"></div>
          Con errores &nbsp;<b style="color:#E53C3C">{errores_total} ({pct_err}%)</b>
        </div>
      </div>

    </div>
    """, unsafe_allow_html=True)
