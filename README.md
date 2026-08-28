# AID Flujos Dealer

Dashboard interno (Streamlit) para validar, antes de subir a **PDN**, que los
tres componentes de un caso de uso documental — **TA** (Text Analyzer,
extracción), **AID** (configuración del flujo) y **UDZ** (eventos) — estén
completos y coherentes entre sí. Trae las Historias de Usuario (HU) desde
Azure DevOps, analiza los JSON adjuntos, y deja un registro (quién analizó,
quién aprobó) antes del despliegue.

## Arranque rápido

1. Copiar `.env.example` a `.env` y completar los valores reales (org de ADO,
   PAT, etc.). El `.env` real nunca se comparte ni se sube a ningún lado.
2. Doble clic en **`run.bat`** — crea el entorno virtual `.venv` la primera
   vez (si no existe) e instala lo necesario, después levanta el dashboard.
3. Se abre en el navegador en `http://localhost:8501`.

Para correr los tests sin levantar la interfaz: doble clic en
**`run_tests.bat`**.

## Estructura del proyecto

```
BANCO/
├── app.py                 # Entry point delgado: st.set_page_config + ui.run_app()
├── core/                     # Toda la lógica (sin layout de Streamlit)
│   ├── __init__.py
│   ├── config.py                # Colores, íconos (ICON_*/MI_*), estados (ESTADO_*), variables de entorno
│   ├── ado_client.py             # Todo lo que habla con Azure DevOps: ado_url(), descargar_hu()
│   ├── analysis.py                # El motor: las 12 validaciones TA/AID/UDZ, analizar_hu/analizar_sprint
│   ├── reports.py                  # Excel consolidado (generar_excel_consolidado) y métricas de ciclo
│   ├── guide.py                     # Texto de la guía contextual paso a paso
│   └── utils.py                      # safe_name, obtener_usuario_actual, get_sprints, abrir_carpeta/archivo
├── ui/                            # Interfaz Streamlit (un módulo por sección de pantalla)
│   ├── __init__.py                  # run_app(): orquesta el orden exacto de renderizado
│   ├── styles.py                     # CSS del design system (inject_css)
│   ├── header.py                      # Header + stepper del pipeline (1→2→3)
│   ├── ingest.py                       # Paso 1 (traer HU) y Paso 2 (analizar sprint)
│   ├── dashboard.py                     # Carga de resultados, KPIs y barra de progreso
│   ├── backlog.py                        # Tarjeta del Excel consolidado + tabla resumen
│   └── hu_detail.py                       # Selector de HU + las 12 validaciones + aprobación (el módulo más grande)
├── run.bat                # Arranca la app (doble clic)
├── run_tests.bat            # Corre los tests (doble clic)
├── requirements.txt
├── .env                     # Credenciales reales — NO se comparte (falta crearlo la primera vez)
├── .env.example               # Plantilla del .env, sin secretos
├── img/
│   └── logo1.png              # Logo que se muestra en el header
├── tests/
│   ├── conftest.py               # Fixtures — importan core.analysis directo (ver "Tests" más abajo)
│   └── test_analisis.py          # Tests de las validaciones TA/AID/UDZ
├── scripts/                   # Reservado — subida a S3/DynamoDB (ver scripts/README.md). Vacío por ahora.
└── Backlog_Dealer/              # Datos de trabajo: HU descargadas + análisis + Excel consolidado.
                                 # Se genera solo, no es código. Ruta configurable via ROOT_FOLDER en .env.
```

**Regla de dependencias:** dentro de `core/`, `config.py` no depende de nada
propio; `utils.py` depende solo de `config`; `analysis.py` depende de
`config` y `utils`; `ado_client.py`/`reports.py`/`guide.py` dependen de los
anteriores (todo con imports relativos, `from .config import ...`). Todo
`ui/` importa de `core` con import absoluto (`from core.analysis import ...`),
nunca al revés. Así cualquier módulo de `core/` se puede importar y probar
sin arrastrar Streamlit de verdad.

`core.ado_client.descargar_hu` y `core.utils.abrir_carpeta`/`abrir_archivo` sí
llaman a `st.warning/error/progress` para dar feedback en vivo — es
intencional (son operaciones interactivas), no lógica de layout.

## Variables de entorno (`.env`)

| Variable | Para qué sirve |
|---|---|
| `ADO_ORG`, `ADO_PROJECT`, `ADO_TEAM`, `ADO_AREA` | Ubicación del proyecto en Azure DevOps |
| `ADO_PAT` | Token de acceso a la API de ADO (permisos de lectura de Work Items) |
| `ITERATION_PATH` | Sprint por defecto al abrir la app |
| `ROOT_FOLDER` | Carpeta local donde se descargan/analizan las HU |
| `DEALER_NAME` | Nombre del ingeniero asignado, para filtrar HU en ADO |

## Trazabilidad y aprobación

Cada análisis guarda **quién** lo corrió y **cuándo** (usuario de Windows,
vía `os.getlogin()`) en `analisis_tecnico.json` dentro de la carpeta de cada
HU. Hay un botón para marcar una HU como **aprobada para PDN**, que también
queda registrado ahí y se refleja en el Excel consolidado (columnas
"Aprobado por" / "Fecha aprobación").

Importante: esto identifica por el usuario de Windows de la sesión donde
corre la app — es trazabilidad básica, no un control de acceso real. Si esto
necesita ser evidencia de auditoría formal, en algún momento va a hacer falta
un login real (SSO/Azure AD) detrás.

## Roadmap (no implementado todavía)

- **Migración a SharePoint**: hoy `Backlog_Dealer/` es una carpeta local
  (`ROOT_FOLDER` en `.env`); la idea es que en el futuro las HU se
  descarguen/suban desde una carpeta sincronizada con SharePoint en vez de
  disco local. No requiere cambios grandes en `app.py` — `ROOT_FOLDER` ya es
  configurable, solo hay que apuntarlo a la carpeta sincronizada.
- **Subida a AWS (S3 / DynamoDB)**: hoy la app solo *valida* que los
  `s3_path` y la config de UDZ sean coherentes, pero no toca AWS de verdad.
  Los scripts que hagan la subida real van a vivir en `scripts/` (ver
  `scripts/README.md`), separados del dashboard.

## Tests

```
run_tests.bat
```

o manualmente:

```
.venv\Scripts\python -m pytest tests\ -v
```

Los tests importan `core.analysis` directo (`import core.analysis`) — no
necesitan `streamlit run` porque ese módulo no tiene layout, solo la lógica de
validación. Incluyen tests contra las HU de ejemplo en `Backlog_Dealer/` y
regresiones específicas de bugs ya encontrados (ver comentarios en
`tests/test_analisis.py`).
