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
│   ├── aws_upload.py               # Subida real de TA/AID/UDZ a DynamoDB QA/PDN (ver "Subida a AWS")
│   ├── reports.py                  # Excel consolidado (generar_excel_consolidado) y métricas de ciclo
│   ├── guide.py                     # Texto de la guía contextual paso a paso
│   └── utils.py                      # safe_name, obtener_usuario_actual, get_sprints, abrir_carpeta/archivo
├── ui/                            # Interfaz Streamlit (un módulo por sección de pantalla)
│   ├── __init__.py                  # run_app(): orquesta el orden exacto de renderizado
│   ├── styles.py                     # CSS del design system (inject_css)
│   ├── header.py                      # Header + stepper del pipeline (1→2→3→4)
│   ├── ingest.py                       # Paso 1 (traer HU) y Paso 2 (analizar sprint)
│   ├── dashboard.py                     # Carga de resultados, KPIs y barra de progreso
│   ├── backlog.py                        # Tarjeta del Excel consolidado + tabla resumen
│   ├── hu_detail.py                       # Selector de HU + las 12 validaciones + aprobación (el módulo más grande)
│   └── aws_console.py                      # Paso 3 del pipeline: consola "Subir a AWS" (ver más abajo)
├── run.bat                # Arranca la app (doble clic)
├── run_tests.bat            # Corre los tests (doble clic)
├── requirements.txt
├── .env                     # Credenciales/config real — NO se comparte (falta crearlo la primera vez)
├── .env.example               # Plantilla del .env, sin secretos
├── aws_credentials.json         # JSON de credenciales AWS (gitignored) — ver "Subida a AWS"
├── img/
│   └── logo1.png              # Logo que se muestra en el header
├── tests/
│   ├── conftest.py               # Fixtures — importan core.analysis directo (ver "Tests" más abajo)
│   └── test_analisis.py          # Tests de las validaciones TA/AID/UDZ
├── scripts/                   # Reservado para scripts sueltos de mantenimiento (ver scripts/README.md).
│                                # La subida a AWS NO vive acá — quedó integrada en core/aws_upload.py.
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
| `AWS_CRED_FILE` | *Opcional.* Ruta al JSON de credenciales AWS. Por default ya apunta a `aws_credentials.json` en la raíz del proyecto — normalmente no hace falta tocarla (ver "Subida a AWS") |
| `AWS_TABLA_{AID,TA,UDZ}_{QA,PDN}` | *Opcionales (6 variables).* Sobreescriben el nombre de una tabla DynamoDB puntual sin tocar código — default en `core/config.py` (ver "Subida a AWS") |

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

## Subida a AWS

Paso 3 del pipeline (después de analizar, antes de aprobar para PDN): sube el
TA/AID/UDZ **activo** de la HU seleccionada a la tabla DynamoDB del ambiente
elegido (QA o PDN). Vive en `core/aws_upload.py` (lógica) + `ui/aws_console.py`
(la consola, sección aparte al final de la página — no anidada en el detalle
de la HU, para que el resultado de cada intento quede siempre visible).

- **Envío siempre real** (no hay modo simulación): si falla la red, las
  credenciales, o falta `boto3`, el error real queda en la consola tipo
  terminal — nunca rompe el resto de la app.
- **Verificación automática**: después de cada `put_item` exitoso, relee el
  mismo item de la tabla (`get_item`) para confirmar que quedó guardado de
  verdad, y lo deja en el log.
- **PDN pide confirmación extra** (checkbox explícito) antes de habilitar el
  botón, por ser escritura en producción.
- **Credenciales**: JSON en `aws_credentials.json` (raíz del proyecto,
  gitignored — mismo formato que ya usa `cargaaws.py`:
  `aws_access_key_id`, `aws_secret_access_key`, `region_name`, y
  `aws_session_token` solo si son credenciales temporales STS). La ruta se
  resuelve por default sin tocar `.env`; solo hace falta `AWS_CRED_FILE` si
  se quiere usar otra ubicación.
- **Dónde cambiar el nombre de una tabla**: los 6 nombres (AID/TA/UDZ ×
  QA/PDN) están en `core/config.py`, diccionario `AWS_TABLAS` — esos son el
  default. Para cambiar uno sin tocar código, se sobreescribe con la variable
  de entorno correspondiente en `.env` (`AWS_TABLA_TA_QA`, etc. — están
  comentadas como ejemplo en `.env.example`).
- **Partition key**: DynamoDB exige que el item tenga un atributo con el
  mismo nombre que la partition key de la tabla. Los JSON de TA/AID/UDZ no
  tienen un campo estándar para esto — si se recrea o cambia una tabla,
  conviene usar un campo que ya exista de forma natural en ese componente
  (`cu_name` para TA, `use_case` para AID, `id` para UDZ son los candidatos
  naturales, ya usados en la validación de "coherencia" entre archivos).

`scripts/` quedó reservado para scripts sueltos de mantenimiento — la subida
a AWS **no** vive ahí, quedó integrada al dashboard porque necesita el
TA/AID/UDZ ya resuelto por `analizar_hu()` y feedback en vivo en la UI.

## Roadmap (no implementado todavía)

- **Migración a SharePoint**: hoy `Backlog_Dealer/` es una carpeta local
  (`ROOT_FOLDER` en `.env`); la idea es que en el futuro las HU se
  descarguen/suban desde una carpeta sincronizada con SharePoint en vez de
  disco local. No requiere cambios grandes en `app.py` — `ROOT_FOLDER` ya es
  configurable, solo hay que apuntarlo a la carpeta sincronizada.
- **Subida a S3**: hoy la app valida que los `s3_path` declarados en AID/UDZ
  sean coherentes entre sí, pero no escribe archivos en S3. Solo se
  implementó la escritura en DynamoDB (ver "Subida a AWS" arriba).

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
