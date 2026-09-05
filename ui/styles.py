"""CSS del design system. Se inyecta una sola vez, al arrancar la app."""
import streamlit as st

from core.config import INK, WHITE, SURFACE, ACCENT, GREEN, PURPLE, ORANGE, RED


def inject_scroll_restore():
    """Streamlit vuelve la página al tope en cada rerun (ej. al elegir otro
    TA/AID/UDZ en el selector, al aprobar, al subir a AWS) — se siente como
    que "la página salta" o "se reinicia". Este script recuerda dónde estaba
    mirando el usuario y lo restaura después de cada rerun.

    No alcanza con guardar el scrollTop en píxeles a secas: si el contenido
    de ARRIBA del punto donde mirabas cambia de alto entre un rerun y el
    siguiente (ej. el log de la consola de AWS creció, o una HU se ocultó de
    la lista de subida masiva porque ya se subió), el mismo píxel absoluto
    termina apuntando a otra parte de la página — se siente como "un salto"
    aunque el scroll técnicamente se haya "restaurado" bien. Por eso se
    ancla a un ELEMENTO real de la página (el primero que estaba tocando el
    borde superior visible) en vez de a un número de píxeles: se guarda una
    "firma" de ese elemento (su data-testid + un pedazo de su texto + un
    contador para el caso de firmas repetidas, ej. varios botones
    "Actualizar") y, al volver, se busca ese mismo elemento y se deja
    exactamente en el mismo lugar de la pantalla donde estaba, sin importar
    cuánto haya crecido o encogido lo que quedó por encima. Si el elemento
    ya no existe (contenido totalmente distinto), cae al píxel absoluto
    como respaldo — mejor que nada.

    Corre dentro de un iframe (así funciona st.iframe con HTML crudo), por
    eso opera sobre window.parent — es la ventana real de la app, no el
    iframe. Y el que hace scroll de verdad NO es la ventana (window.scrollY
    se queda siempre en 0) sino el contenedor interno [data-testid="stMain"]
    — así que se apunta directo a ese elemento, con window como respaldo por
    si una versión futura de Streamlit cambia esa estructura."""
    st.iframe("""
    <script>
    (function() {
        const KEY_Y = "aid_dealer_scroll_y";
        const KEY_ANCLA = "aid_dealer_scroll_ancla";
        // Elementos "anclables": los bloques de contenido/widgets más comunes
        // de Streamlit — suficiente granularidad para no perder el lugar sin
        // tener que anclar a cada nodo del DOM.
        const SELECTOR = '[data-testid="stMarkdown"], [data-testid="stButton"], ' +
            '[data-testid="stCheckbox"], [data-testid="stTextInput"], ' +
            '[data-testid="stSelectbox"], [data-testid="stRadio"], ' +
            '[data-testid="stExpander"], [data-testid="stAlert"], ' +
            '[data-testid="stDataFrame"], [data-testid="stTabs"]';

        function contenedor() {
            try {
                return window.parent.document.querySelector('[data-testid="stMain"]') || window.parent;
            } catch (e) { return null; }
        }
        function candidatos(doc) {
            try { return Array.from(doc.querySelectorAll(SELECTOR)); } catch (e) { return []; }
        }
        // "Firma" estable de un elemento: qué tipo de widget es + un pedazo
        // de su texto — y un contador para distinguir firmas repetidas (ej.
        // varios botones "Actualizar" en la misma pantalla).
        function firma(el, contador) {
            const tid = el.getAttribute('data-testid') || el.tagName;
            const texto = (el.innerText || '').trim().slice(0, 50);
            const base = tid + '|' + texto;
            const n = contador[base] || 0;
            contador[base] = n + 1;
            return base + '#' + n;
        }

        function guardar() {
            try {
                const el = contenedor();
                if (!el) return;
                sessionStorage.setItem(KEY_Y, el.scrollTop || el.scrollY || 0);

                const doc = window.parent.document;
                const contRect = el.getBoundingClientRect();
                const contador = {};
                for (const nodo of candidatos(doc)) {
                    const f = firma(nodo, contador);
                    const offset = nodo.getBoundingClientRect().top - contRect.top;
                    // Primer elemento cuyo borde superior toca (o pasó) el
                    // techo visible del contenedor — es "lo que se está mirando".
                    if (offset >= -4) {
                        sessionStorage.setItem(KEY_ANCLA, JSON.stringify({firma: f, offset: offset}));
                        return;
                    }
                }
                sessionStorage.removeItem(KEY_ANCLA);
            } catch (e) {}
        }

        function restaurar() {
            try {
                const el = contenedor();
                if (!el) return;
                const raw = sessionStorage.getItem(KEY_ANCLA);
                if (raw) {
                    const guardado = JSON.parse(raw);
                    const doc = window.parent.document;
                    const contador = {};
                    for (const nodo of candidatos(doc)) {
                        if (firma(nodo, contador) === guardado.firma) {
                            const contRect = el.getBoundingClientRect();
                            const actual = nodo.getBoundingClientRect().top - contRect.top;
                            el.scrollTop = el.scrollTop + (actual - guardado.offset);
                            return;
                        }
                    }
                }
                // Ancla no encontrada (contenido totalmente distinto): al
                // menos vuelve al mismo píxel de antes.
                const y = sessionStorage.getItem(KEY_Y);
                if (y !== null) { el.scrollTo(0, parseInt(y, 10)); }
            } catch (e) {}
        }

        // Se reintenta un par de veces: el contenido nuevo puede seguir
        // creciendo de alto un instante después del primer render.
        setTimeout(restaurar, 30);
        setTimeout(restaurar, 150);
        setTimeout(restaurar, 400);

        let guardarPendiente = false;
        function guardarThrottled() {
            if (guardarPendiente) return;
            guardarPendiente = true;
            (window.parent.requestAnimationFrame || window.requestAnimationFrame)(() => {
                guardar();
                guardarPendiente = false;
            });
        }
        try {
            const el = contenedor();
            if (el) { el.addEventListener("scroll", guardarThrottled, { passive: true }); }
        } catch (e) {}
    })();
    </script>
    """, height=1)


def inject_css():
    st.markdown(f"""
<style>

/* =======================================================================
 DESIGN SYSTEM - DEALER AUTOMATION
 ======================================================================= */

:root {{
 --ink: {INK};
 --white: {WHITE};
 --surface: {SURFACE};
 --accent: {ACCENT};
 --green: {GREEN};
 --purple: {PURPLE};
 --orange: {ORANGE};
 --pink: #F472B6;
 --sky: #38BDF8;
 --red: {RED};

 --line: #E7E5E4;
 --muted: #78716C;
 --track: #F5F5F4;

 --shadow-sm: 0 2px 6px rgba(0,0,0,.04);
 --shadow-md: 0 8px 25px rgba(0,0,0,.06);
}}

/* =======================================================================
 APP
 ======================================================================= */

html, body, [class*="css"] {{
 font-family: "Segoe UI", sans-serif;
}}

/* stHeader queda visible (antes se ocultaba) para no tapar el menú de
   Streamlit: ahí está el selector de tema (claro/oscuro/colores) y el
   indicador de "running" cuando la app se está re-ejecutando. */
[data-testid="stHeader"] {{
 background: transparent;
}}

.block-container {{
 max-width: 1500px;
 padding-top: 1.2rem;
 padding-bottom: 2rem;
 padding-left: 2rem;
 padding-right: 2rem;
}}

/* =======================================================================
 SIDEBAR
 ======================================================================= */

section[data-testid="stSidebar"] {{
 background: #1a1917;
 border-right: 1px solid var(--line);
}}

section[data-testid="stSidebar"] .block-container {{
 padding-top: 1rem;
}}

section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] h4,
section[data-testid="stSidebar"] h5,
section[data-testid="stSidebar"] h6,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stTextInput label,
section[data-testid="stSidebar"] .stSelectbox label {{
 color: white !important;
}}

section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span {{
 color: #CCCCCC !important;
}}

/* =======================================================================
 HEADER
 ======================================================================= */

.app-header {{
 background: white;
 border: 1px solid var(--line);
 border-radius: 18px;
 padding: 24px;
 margin-bottom: 1.25rem;

 position: relative;
 overflow: hidden;

 display: flex;
 justify-content: space-between;
 align-items: center;

 box-shadow: var(--shadow-sm);
}}

.app-header::before {{
 content: "";
 position: absolute;
 left: 0;
 top: 0;
 bottom: 0;
 width: 6px;
 background: var(--accent);
}}

.app-header-title {{
 color: var(--ink);
 font-size: 30px;
 font-weight: 800;
 letter-spacing: -0.02em;
 margin: 0;
}}

.app-header-subtitle {{
 color: var(--muted);
 font-size: 14px;
 margin-top: 4px;
 margin-bottom: 0;
}}

.app-badge {{
 background: var(--ink);
 color: white;
 padding: 8px 14px;
 border-radius: 999px;
 font-size: 0.72rem;
 font-weight: 700;
 text-transform: uppercase;
}}

/* =======================================================================
 SECTION TITLES
 ======================================================================= */

.spyra-section-title {{
 display: flex;
 align-items: center;
 gap: 10px;
 font-weight: 800;
 color: var(--ink);
 margin-top: 1rem;
 margin-bottom: 0.8rem;
}}

.spyra-section-title::before {{
 content: "";
 width: 5px;
 height: 18px;
 background: var(--accent);
 border-radius: 999px;
}}

/* =======================================================================
 PIPELINE STEPPER (flujo Traer -> Analizar -> Revisar)
 ======================================================================= */

.pipeline-stepper {{
 display: flex;
 align-items: center;
 gap: 8px;
 margin-bottom: 1rem;
 flex-wrap: wrap;
}}

.pipeline-step {{
 display: flex;
 align-items: center;
 gap: 8px;
 padding: 7px 14px 7px 8px;
 border-radius: 999px;
 background: var(--track);
 border: 1px solid var(--line);
 font-size: 12.5px;
 font-weight: 700;
 color: var(--muted);
}}

.pipeline-step.active {{
 background: white;
 border-color: var(--accent);
 color: var(--ink);
 box-shadow: var(--shadow-sm);
}}

.pipeline-step.done {{
 background: #D1FAE5;
 border-color: var(--green);
 color: #065F46;
}}

.pipeline-step-num {{
 display: inline-flex;
 align-items: center;
 justify-content: center;
 width: 20px;
 height: 20px;
 border-radius: 50%;
 background: var(--line);
 color: var(--muted);
 font-size: 11px;
 font-weight: 800;
 flex-shrink: 0;
}}

.pipeline-step.active .pipeline-step-num {{
 background: var(--accent);
 color: #1a1917;
}}

.pipeline-step.done .pipeline-step-num {{
 background: var(--green);
 color: white;
}}

.pipeline-arrow {{
 color: var(--line);
 font-size: 15px;
 font-weight: 700;
}}

/* =======================================================================
 STEP CARD LABEL (encabezado de cada bloque del pipeline)
 ======================================================================= */

.step-card-label {{
 background: white;
 border: 1px solid var(--line);
 border-left: 4px solid var(--accent);
 color: var(--ink);
 font-weight: 700;
 font-size: 13px;
 padding: 10px 14px;
 border-radius: 8px;
 margin-bottom: 0.6rem;
}}

.step-card-label .step-sub {{
 color: var(--muted);
 font-weight: 600;
 font-size: 12px;
}}

.step-card-help {{
 color: var(--muted);
 font-size: 11.5px;
 margin: 0 0 0.6rem 2px;
}}

/* =======================================================================
 KPI
 ======================================================================= */

.spyra-kpi {{
 background: white;
 border: 1px solid var(--line);
 border-radius: 18px;
 padding: 18px;
 box-shadow: var(--shadow-sm);
 transition: 0.15s ease;
}}

.spyra-kpi:hover {{
 transform: translateY(-2px);
 box-shadow: var(--shadow-md);
}}

.spyra-kpi-label {{
 color: var(--muted);
 text-transform: uppercase;
 font-size: 0.72rem;
 font-weight: 700;
}}

.spyra-kpi-value {{
 color: var(--ink);
 font-size: 32px;
 font-weight: 800;
 line-height: 1;
 margin-top: 8px;
}}

.spyra-kpi-sub {{
 margin-top: 8px;
 color: var(--muted);
 font-size: 0.78rem;
}}

.spyra-border-green {{
 border-top: 4px solid var(--green);
}}

.spyra-border-orange {{
 border-top: 4px solid var(--orange);
}}

.spyra-border-purple {{
 border-top: 4px solid var(--purple);
}}

.spyra-border-dark {{
 border-top: 4px solid var(--ink);
}}

/* =======================================================================
 STATUS BADGES
 ======================================================================= */

.spyra-badge {{
 display: inline-flex;
 align-items: center;
 justify-content: center;
 padding: 4px 10px;
 border-radius: 999px;
 font-size: 0.7rem;
 font-weight: 700;
}}

.spyra-success {{
 background: #D4F5E9;
 color: #156F48;
}}

.spyra-danger {{
 background: #FDE2E2;
 color: #B42318;
}}

.spyra-warning {{
 background: #FFF1D6;
 color: #B45309;
}}

.spyra-info {{
 background: #DFF4FB;
 color: #0C6E8E;
}}

/* =======================================================================
 TABLES
 ======================================================================= */

[data-testid="stDataFrame"] {{
 border: 1px solid var(--line);
 border-radius: 18px;
 overflow: hidden;
 box-shadow: var(--shadow-sm);
}}

/* =======================================================================
 EXPANDERS
 ======================================================================= */

.streamlit-expanderHeader {{
 border: 1px solid var(--line) !important;
 background: white !important;
 border-radius: 14px !important;
 font-weight: 700 !important;
}}

.streamlit-expanderContent {{
 border-left: 1px solid var(--line);
 border-right: 1px solid var(--line);
 border-bottom: 1px solid var(--line);
 border-radius: 0 0 14px 14px;
}}

/* =======================================================================
 BUTTONS
 ======================================================================= */

/* Descendiente (no hijo directo): un botón con help= agrega un wrapper de
   tooltip entre .stButton y <button>, y el combinador ">" no lo alcanza. */
.stButton button {{
 border: none !important;
 border-radius: 12px !important;
 background: #FDDA24 !important;
 color: #000000 !important;
 font-weight: 700 !important;
 min-height: 42px;
 transition: 0.15s ease;
}}

.stButton button * {{
 color: #000000 !important;
}}

.stButton button span {{
 color: #000000 !important;
}}

.stButton button:hover {{
 transform: translateY(-1px);
 background: #FFE152 !important;
 color: #000000 !important;
 box-shadow: var(--shadow-md);
}}

section[data-testid="stSidebar"] .stButton button {{
 background: #FDDA24 !important;
 color: #000000 !important;
 font-weight: 700 !important;
}}

section[data-testid="stSidebar"] .stButton button * {{
 color: #000000 !important;
}}

section[data-testid="stSidebar"] .stButton button span {{
 color: #000000 !important;
}}

section[data-testid="stSidebar"] .stButton button:hover {{
 background: #FFE152 !important;
 color: #000000 !important;
}}

/* =======================================================================
 INPUTS
 ======================================================================= */

div[data-baseweb="select"] > div {{
 border-radius: 12px !important;
 background: white !important;
}}

.stTextInput input {{
 border-radius: 12px !important;
 background: white !important;
 color: var(--ink) !important;
}}

section[data-testid="stSidebar"] div[data-baseweb="select"] > div {{
 background: #2a2825 !important;
 border: 1px solid #3a3835 !important;
 color: white !important;
 padding: 8px !important;
}}

section[data-testid="stSidebar"] div[data-baseweb="select"] div {{
 color: white !important;
}}

section[data-testid="stSidebar"] div[data-baseweb="select"] svg {{
 fill: white !important;
}}

section[data-testid="stSidebar"] [role="combobox"] {{
 background: #2a2825 !important;
 border: 1px solid #3a3835 !important;
 color: white !important;
}}

section[data-testid="stSidebar"] [role="combobox"] span {{
 color: white !important;
}}

/* =======================================================================
 ALERTS
 ======================================================================= */

.stAlert {{
 border-radius: 12px !important;
}}

section[data-testid="stSidebar"] .stSuccess {{
 background: #00D4A0 !important;
 color: white !important;
 padding: 12px !important;
 border-radius: 8px !important;
 font-weight: 600 !important;
 border: 1px solid #00E8B6 !important;
}}

section[data-testid="stSidebar"] .stError {{
 background: #FF3333 !important;
 color: white !important;
 padding: 12px !important;
 border-radius: 8px !important;
 font-weight: 600 !important;
 border: 1px solid #FF5555 !important;
}}

section[data-testid="stSidebar"] .stWarning {{
 background: #FF8C00 !important;
 color: white !important;
 padding: 12px !important;
 border-radius: 8px !important;
 font-weight: 600 !important;
 border: 1px solid #FFA500 !important;
}}

section[data-testid="stSidebar"] .stInfo {{
 background: #1E90FF !important;
 color: white !important;
 padding: 12px !important;
 border-radius: 8px !important;
 font-weight: 600 !important;
 border: 1px solid #4DA3FF !important;
}}

/* =======================================================================
 PROGRESS CARD
 ======================================================================= */

.spyra-progress-card {{
 background: white;
 border: 1px solid var(--line);
 border-radius: 18px;
 padding: 20px 24px;
 box-shadow: var(--shadow-sm);
 text-align: left;
}}

.spyra-progress-card b {{
 color: var(--ink);
 font-size: 14px;
 display: block;
 margin-bottom: 12px;
}}

.spyra-bar {{
 width: 100%;
 height: 12px;
 background: var(--track);
 border-radius: 999px;
 overflow: hidden;
 margin-bottom: 12px;
 margin-left: auto;
 margin-right: auto;
}}

.spyra-bar span {{
 display: block;
 height: 100%;
 background: #FDDA24;
 border-radius: 999px;
 transition: width 0.3s ease;
 box-shadow: 0 2px 8px rgba(253, 218, 36, 0.3);
}}

.spyra-pill {{
 display: inline-block;
 background: #FDDA24;
 color: #1a1917;
 padding: 6px 12px;
 border-radius: 999px;
 font-size: 0.75rem;
 font-weight: 700;
}}

/* =======================================================================
 VALIDATION CARDS
 ======================================================================= */

.val-card {{
 background: white;
 border: 1px solid var(--line);
 border-left: 4px solid var(--line);
 border-radius: 12px;
 padding: 14px 16px;
 margin-bottom: 10px;
 box-shadow: var(--shadow-sm);
}}

.val-card.ok  {{ border-left-color: var(--green); }}
.val-card.err {{ border-left-color: var(--red); background: #FFFBFB; }}
.val-card.warn {{ border-left-color: var(--orange); background: #FFFDF8; }}

.val-card-header {{
 display: flex;
 align-items: center;
 justify-content: space-between;
 gap: 12px;
 margin-bottom: 4px;
}}

.val-card-title {{
 font-size: 13.5px;
 font-weight: 700;
 color: var(--ink);
 display: flex;
 align-items: center;
 gap: 8px;
}}

.val-card-file {{
 display: inline-block;
 background: #F5F3FF;
 color: #6D28D9;
 border: 1px solid #DDD6FE;
 padding: 3px 9px;
 border-radius: 999px;
 font-size: 10.5px;
 font-weight: 700;
 white-space: nowrap;
}}

.val-card-sub {{
 font-size: 11.5px;
 color: var(--muted);
 margin-top: 2px;
}}

.val-card-field {{
 display: inline-block;
 background: var(--track);
 border: 1px solid var(--line);
 color: #57534E;
 font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
 font-size: 10.5px;
 padding: 1px 7px;
 border-radius: 5px;
 white-space: nowrap;
}}

.val-card-valor {{
 color: #15803D;
 font-weight: 700;
 font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
 font-size: 11px;
 margin-left: 6px;
}}

/* Encabezado de grupo (TA / AID / UDZ / Cruzadas) dentro de Validaciones críticas */
.val-group-title {{
 font-size: 11px;
 font-weight: 800;
 letter-spacing: .06em;
 text-transform: uppercase;
 color: var(--muted);
 margin: 18px 0 8px 2px;
 display: flex;
 align-items: center;
 gap: 8px;
}}

.val-group-title::after {{
 content: "";
 flex: 1;
 height: 1px;
 background: var(--line);
}}

/* Resumen corto (encontrado / falta) antes de Archivos y adjuntos */
.resumen-box {{
 border-radius: 10px;
 padding: 10px 14px;
 height: 100%;
 box-sizing: border-box;
}}

.resumen-box.ok {{
 background: #D1FAE5;
 border: 1px solid var(--green);
}}

.resumen-box.err {{
 background: #FEF2F2;
 border: 1px solid #FCA5A5;
}}

.resumen-box-title {{
 font-size: 11px;
 font-weight: 800;
 letter-spacing: .04em;
 text-transform: uppercase;
 color: var(--ink);
 margin-bottom: 3px;
}}

.resumen-box-body {{
 font-size: 12.5px;
 color: #44403C;
 line-height: 1.5;
}}

/*  Contador de validaciones  */
.val-summary {{
 display: flex;
 gap: 10px;
 margin-bottom: 14px;
 padding: 12px 16px;
 background: var(--track);
 border-radius: 10px;
 border: 1px solid var(--line);
}}

.val-summary-item {{
 display: flex;
 align-items: center;
 gap: 6px;
 font-size: 12.5px;
 font-weight: 700;
 color: var(--ink);
}}

.val-summary-dot {{
 width: 10px;
 height: 10px;
 border-radius: 50%;
 flex-shrink: 0;
}}

.val-summary-dot.ok   {{ background: var(--green); }}
.val-summary-dot.err  {{ background: var(--red); }}
.val-summary-dot.warn {{ background: var(--orange); }}

/*  HU Header card  */
.hu-detail-header {{
 background: white;
 border: 1px solid var(--line);
 border-radius: 14px;
 padding: 16px 20px;
 margin-bottom: 16px;
 box-shadow: var(--shadow-sm);
 display: flex;
 align-items: flex-start;
 justify-content: space-between;
 gap: 16px;
}}

.hu-detail-id {{
 font-size: 11px;
 font-weight: 700;
 text-transform: uppercase;
 letter-spacing: .08em;
 color: var(--muted);
 margin-bottom: 4px;
}}

.hu-detail-title {{
 font-size: 15px;
 font-weight: 800;
 color: var(--ink);
 line-height: 1.3;
}}

.hu-detail-chips {{
 display: flex;
 flex-wrap: wrap;
 gap: 6px;
 margin-top: 10px;
}}

.hu-chip {{
 background: var(--track);
 border: 1px solid var(--line);
 border-radius: 999px;
 padding: 3px 8px;
 font-size: 11px;
 font-weight: 600;
 color: var(--muted);
 max-width: 180px;
 overflow: hidden;
 text-overflow: ellipsis;
 white-space: nowrap;
 display: inline-block;
 vertical-align: middle;
}}

.hu-chip b {{ color: var(--ink); }}

/*  Estado vacío  */
.empty-state {{
 text-align: center;
 padding: 36px 20px;
 color: var(--muted);
}}

.empty-state-icon {{
 width: 40px;
 height: 40px;
 margin: 0 auto 12px;
 color: var(--line);
}}

.empty-state-icon svg {{
 width: 100%;
 height: 100%;
}}

.empty-state-title {{
 font-size: 18px;
 font-weight: 700;
 color: var(--ink);
 margin-bottom: 8px;
}}

.empty-state-sub {{
 font-size: 13px;
 line-height: 1.6;
}}

/*  Resumen ejecutivo inline  */
.exec-banner {{
 display: flex;
 align-items: center;
 justify-content: space-between;
 background: white;
 border: 1px solid var(--line);
 border-radius: 12px;
 padding: 12px 18px;
 margin-bottom: 12px;
 box-shadow: var(--shadow-sm);
}}

.exec-banner-text {{
 font-size: 13.5px;
 font-weight: 700;
 color: var(--ink);
}}

.exec-banner-sub {{
 font-size: 12px;
 color: var(--muted);
 margin-top: 2px;
}}

.exec-banner.ok   {{ border-left: 4px solid var(--green); }}
.exec-banner.err  {{ border-left: 4px solid var(--red); }}
.exec-banner.warn {{ border-left: 4px solid var(--orange); }}

/*  RNF card  */
.rnf-card {{
 background: white;
 border: 1px solid var(--line);
 border-radius: 12px;
 padding: 14px 18px;
 margin-bottom: 8px;
 display: flex;
 align-items: center;
 gap: 14px;
 box-shadow: var(--shadow-sm);
}}

.rnf-card.ok   {{ border-left: 4px solid var(--green); }}
.rnf-card.miss {{ border-left: 4px solid var(--red); background: #FFFBFB; }}

.rnf-icon {{ font-size: 22px; flex-shrink: 0; }}

.rnf-info-title {{
 font-size: 13px;
 font-weight: 700;
 color: var(--ink);
}}

.rnf-info-sub {{
 font-size: 11.5px;
 color: var(--muted);
 margin-top: 2px;
}}

/* =======================================================================
 CONSOLA "SUBIR A AWS"
 ======================================================================= */

.aws-card {{
 background: white;
 border: 1px solid var(--line);
 border-left: 4px solid var(--line);
 border-radius: 12px;
 padding: 14px 16px;
 box-shadow: var(--shadow-sm);
 /* TA/AID/UDZ tienen criterios y nombres de tabla de largo distinto, así
    que cada tarjeta ocupa una cantidad de líneas distinta — sin un piso de
    altura común, el botón "Subir..." de abajo queda a una altura diferente
    en cada columna. Con esto, aunque el contenido varíe, siempre arranca
    en el mismo lugar (ajustado al caso más corto — AID, el más largo, puede
    superarlo sin problema, ahí sí manda su propio contenido).
 */
 min-height: 96px;
 box-sizing: border-box;
}}

.aws-card.ok   {{ border-left-color: var(--green); }}
.aws-card.warn {{ border-left-color: var(--orange); background: #FFFDF8; }}
.aws-card.na   {{ border-left-color: var(--line); }}

.aws-card-title {{
 font-size: 13.5px;
 font-weight: 800;
 display: flex;
 align-items: center;
 gap: 6px;
 margin-bottom: 4px;
}}

.aws-card-criterio {{
 font-size: 11px;
 color: var(--muted);
 line-height: 1.5;
 margin-bottom: 8px;
}}

.aws-table-tag {{
 display: block;
 font-size: 10.5px;
 font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
 color: #374151;
 background: var(--track);
 border: 1px solid var(--line);
 border-radius: 6px;
 padding: 4px 8px;
 margin-bottom: 10px;
 word-break: break-all;
}}

.aws-console-wrap {{
 border-radius: 12px;
 overflow: hidden;
 box-shadow: var(--shadow-md);
 border: 1px solid #000;
}}

.aws-console-bar {{
 background: #2B2B2B;
 padding: 9px 14px;
 display: flex;
 align-items: center;
 gap: 6px;
}}

.aws-console-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
.aws-console-dot.red    {{ background: #FF5F56; }}
.aws-console-dot.yellow {{ background: #FFBD2E; }}
.aws-console-dot.green  {{ background: #27C93F; }}

.aws-console-bar-label {{
 margin-left: 8px;
 font-size: 11px;
 font-weight: 600;
 letter-spacing: .02em;
 color: #9CA3AF;
 font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}}

.aws-console {{
 background: #1E1E1E;
 padding: 18px 20px;
 max-height: 480px;
 min-height: 140px;
 overflow-y: auto;
 font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
 font-size: 12.5px;
 line-height: 1.9;
}}

.aws-console-ts {{
 color: #6B7280;
 margin-right: 10px;
 font-size: 11px;
}}

.aws-console-icon {{
 display: inline-block;
 width: 16px;
 margin-right: 4px;
 font-weight: 700;
 text-align: center;
}}

.aws-console-line {{ color: #D4D4D4; white-space: pre-wrap; word-break: break-all; }}
.aws-console-line.err  {{ color: #F87171; font-weight: 600; }}
.aws-console-line.err  .aws-console-icon {{ color: #F87171; }}
.aws-console-line.warn {{ color: #FBBF24; font-weight: 600; }}
.aws-console-line.warn .aws-console-icon {{ color: #FBBF24; }}
.aws-console-line.ok   {{ color: #4ADE80; font-weight: 600; }}
.aws-console-line.ok   .aws-console-icon {{ color: #4ADE80; }}
.aws-console-line.sep  {{
 color: #E5E7EB;
 font-weight: 700;
 font-size: 11px;
 letter-spacing: .03em;
 text-transform: uppercase;
 margin: 10px 0 6px;
 padding-bottom: 6px;
 border-bottom: 1px solid #3F3F3F;
}}
.aws-console-empty {{ color: #6B7280; font-style: italic; }}

.aws-alert {{
 background: #FEF3C7;
 border: 1px solid #FDE68A;
 border-radius: 8px;
 padding: 8px 10px;
 margin: 8px 0;
 font-size: 11px;
 line-height: 1.5;
 color: #92400E;
}}

.aws-alert code {{
 background: rgba(0,0,0,.06);
 padding: 1px 5px;
 border-radius: 4px;
 font-size: 10.5px;
}}

.aws-chip {{
 display: inline-block;
 background: #D1FAE5;
 border: 1px solid #6EE7B7;
 border-radius: 999px;
 padding: 3px 9px;
 font-size: 10.5px;
 font-weight: 600;
 color: #065F46;
 margin-top: 6px;
}}

.aws-chip b {{ font-weight: 800; }}

.aws-summary-strip {{
 display: flex;
 align-items: center;
 justify-content: space-between;
 flex-wrap: wrap;
 gap: 10px;
 background: white;
 border: 1px solid var(--line);
 border-radius: 12px;
 padding: 10px 16px;
 margin-bottom: 12px;
 box-shadow: var(--shadow-sm);
}}

.aws-summary-text {{
 font-size: 13px;
 font-weight: 700;
 color: var(--ink);
}}

</style>
""", unsafe_allow_html=True)
