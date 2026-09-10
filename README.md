# AID Flujos Dealer

Dashboard interno (Streamlit) para validar, antes de subir a **PDN**, que los
tres componentes de un caso de uso documental — **TA** (Text Analyzer,
extracción), **AID** (configuración del flujo) y **UDZ** (eventos) — estén
completos y coherentes entre sí. Trae las Historias de Usuario (HU) desde
Azure DevOps, analiza los JSON adjuntos, y deja un registro (quién analizó,
quién subió cada componente y a qué ambiente) antes del despliegue.

## Arranque rápido

1. Copiar `.env.example` a `.env` y completar los valores reales (org de ADO,
   PAT, etc. — ver "Primeros pasos para un dealer nuevo" más abajo si es la
   primera vez que usás esta herramienta). El `.env` real nunca se comparte
   ni se sube a ningún lado.
2. Doble clic en **`run.bat`** — crea el entorno virtual `.venv` la primera
   vez (si no existe) e instala lo necesario, después levanta el dashboard.
   Si te sirve un acceso directo en el escritorio, apuntalo a `run.bat` y
   usá `img/logo1.ico` como ícono.
3. Se abre en el navegador en `http://localhost:8501`.

Para correr los tests sin levantar la interfaz: doble clic en
**`run_tests.bat`**.

## Primeros pasos para un dealer nuevo

Si es la primera vez que corrés esta herramienta (traspaso, PC nueva, etc.),
en ese orden:

1. **PAT de Azure DevOps propio** — generá tu propio Personal Access Token
   (permisos de lectura sobre Work Items). No reutilices el de otra persona:
   cada PAT es personal y queda asociado a esa identidad en la auditoría de ADO.
2. **Tu nombre exacto en `DEALER_NAME`** — tiene que coincidir letra por
   letra con cómo figurás en el campo "Assigned To" de Azure DevOps. Si no
   coincide, el Paso 1 solo te va a traer HU sin asignar, nunca las tuyas.
3. **`ROOT_FOLDER`** — no hace falta definirlo: por default apunta a una
   carpeta `Backlog_Dealer` al lado del proyecto, vacía. Si en cambio vas a
   continuar un backlog que ya existía (HU ya descargadas/analizadas por otra
   persona), hay que copiarte esa carpeta aparte — no viaja con el código.
4. **Credenciales de AWS** (`aws_credentials.json`) — necesarias solo para
   "Subir a AWS" (Paso 3), no para descargar/analizar HU. Son temporales: se
   cargan desde el panel "Credenciales AWS" dentro de la consola de subida,
   sin editar ningún archivo a mano, y hay que repetirlo cada vez que la
   sesión vence. Si todavía no tenés acceso a PDN, podés seguir subiendo a
   QA sin problema, y usar la confirmación manual (ver "Recuperar el estado
   de PDN" más abajo) para dejar constancia mientras tanto.
5. Levantar la app, elegir el sprint en "Paso 1", tocar "Descargar HU" y
   confirmar que aparecen tus HU asignadas.

## Estructura del proyecto

```
BANCO/
├── app.py                 # Entry point delgado: st.set_page_config + ui.run_app()
├── core/                     # Toda la lógica (sin layout de Streamlit)
│   ├── __init__.py
│   ├── config.py                # Colores, íconos (ICON_*/MI_*), estados (ESTADO_*), variables de entorno
│   ├── ado_client.py             # Todo lo que habla con Azure DevOps: ado_url(), descargar_hu()
│   ├── analysis.py                # El motor: las 12 validaciones TA/AID/UDZ, analizar_hu/analizar_sprint
│   ├── aws_upload.py               # Subida real de TA/AID/UDZ a DynamoDB QA/PDN + verificar_en_tabla (ver "Subida a AWS")
│   ├── reports.py                  # Excel consolidado (generar_excel_consolidado) y métricas de ciclo
│   ├── guide.py                     # Texto de la guía contextual paso a paso
│   └── utils.py                      # safe_name, obtener_usuario_actual, get_sprints, encontrar_hu_folder, abrir_carpeta/archivo
├── ui/                            # Interfaz Streamlit (un módulo por sección de pantalla)
│   ├── __init__.py                  # run_app(): orquesta el orden exacto de renderizado
│   ├── styles.py                     # CSS del design system (inject_css)
│   ├── header.py                      # Header + stepper del pipeline (1→2→3→4)
│   ├── ingest.py                       # Paso 1 (traer HU) y Paso 2 (analizar sprint)
│   ├── dashboard.py                     # Carga de resultados, KPIs y barra de progreso
│   ├── backlog.py                        # Tarjeta del Excel consolidado + tabla resumen
│   ├── hu_detail.py                       # Selector de HU + las 12 validaciones + estado de PDN (el módulo más grande)
│   └── aws_console.py                      # Paso 3 del pipeline: consola "Subir a AWS" (ver más abajo)
├── run.bat                # Arranca la app (doble clic)
├── run_tests.bat            # Corre los tests (doble clic)
├── requirements.txt          # Versiones fijas — ver "Dependencias"
├── .env                     # Credenciales/config real — NO se comparte (falta crearlo la primera vez)
├── .env.example               # Plantilla del .env, sin secretos
├── aws_credentials.json         # JSON de credenciales AWS (gitignored) — ver "Subida a AWS"
├── img/
│   ├── logo1.png               # Logo que se muestra en el header
│   └── logo1.ico                # Mismo logo en .ico, para usar como ícono de acceso directo
├── docs/
│   └── PROPUESTA_MULTIUSUARIO.md  # Arquitectura propuesta para llevar esto a varios dealers a la vez
├── tests/
│   ├── conftest.py               # Fixtures — importan core.analysis directo (ver "Tests" más abajo)
│   └── test_analisis.py          # Tests de las validaciones TA/AID/UDZ
└── Backlog_Dealer/              # Datos de trabajo: HU descargadas + análisis + Excel consolidado + cargas directas.
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

## Dependencias

`requirements.txt` fija versiones exactas (no rangos abiertos), a propósito:
así quien clone el proyecto instala exactamente lo mismo que ya está probado,
sin arriesgarse a que una versión nueva de Streamlit/pandas rompa algo el día
que alguien nuevo instale desde cero. Para actualizar una versión a propósito,
cambiarla acá y volver a correr los tests antes de confirmar que sigue andando.

## Variables de entorno (`.env`)

| Variable | Para qué sirve |
|---|---|
| `ADO_ORG`, `ADO_PROJECT`, `ADO_TEAM`, `ADO_AREA` | Ubicación del proyecto en Azure DevOps |
| `ADO_PAT` | Token de acceso a la API de ADO (permisos de lectura de Work Items) — personal, no se comparte entre personas |
| `ITERATION_PATH` | Sprint por defecto al abrir la app. El desplegable de "Paso 1" muestra un rango dinámico alrededor de este sprint (±2/+3) — alcanza con actualizar este número cada sprint nuevo, no hay lista fija que mantener |
| `ROOT_FOLDER` | *Opcional.* Carpeta donde se descargan/analizan las HU. Por default es `Backlog_Dealer` junto al proyecto (no una ruta fija de una PC en particular) |
| `DEALER_NAME` | Nombre del ingeniero asignado — debe coincidir exacto con "Assigned To" en ADO, para filtrar HU |
| `AWS_CRED_FILE` | *Opcional.* Ruta al JSON de credenciales AWS. Por default ya apunta a `aws_credentials.json` en la raíz del proyecto — normalmente no hace falta tocarla (ver "Subida a AWS") |
| `AWS_TABLA_{AID,TA,UDZ}_{QA,PDN}` | *Opcionales (6 variables).* Sobreescriben el nombre de una tabla DynamoDB puntual sin tocar código — default en `core/config.py` (ver "Subida a AWS") |

## Trazabilidad

Cada análisis guarda **quién** lo corrió y **cuándo** (usuario de Windows,
vía `os.getlogin()`) en `analisis_tecnico.json` dentro de la carpeta de cada
HU. Hay un botón opcional para marcar una HU como **probada en QA**, que
queda registrado ahí y se refleja en el resumen para ADO.

**"Desplegado en PDN" no es un checkbox manual** — se calcula solo, mirando
si TA/AID/UDZ (todos los presentes en la HU) ya se subieron con éxito a la
tabla de PDN real (`core.analysis.obtener_estado_pdn_real`). QA y PDN se
registran por separado por componente: subir algo a QA después de haberlo
subido a PDN no borra el estado de PDN.

**Recuperar el estado de PDN** (si por algún motivo se perdió, o para
confirmarlo sin haber subido nada desde acá): en el detalle de la HU, cuando
falta confirmación de PDN, aparece un expander con dos opciones — verificar
directo contra la tabla real de AWS (`core.aws_upload.verificar_en_tabla`,
solo lectura, necesita credenciales con acceso de lectura a PDN), o
confirmarlo a mano dejando motivo y fecha real si no tenés ese acceso a mano.

Importante: esto identifica por el usuario de Windows de la sesión donde
corre la app — es trazabilidad básica, no un control de acceso real. Si esto
necesita ser evidencia de auditoría formal, en algún momento va a hacer falta
un login real (SSO/Azure AD) detrás — ver `docs/PROPUESTA_MULTIUSUARIO.md`.

## Subida a AWS

Paso 3 del pipeline (después de analizar, antes de confirmar PDN): sube
TA/AID/UDZ a la tabla DynamoDB del ambiente elegido (QA o PDN). Vive en
`core/aws_upload.py` (lógica) + `ui/aws_console.py` (la consola, sección
aparte al final de la página). Tiene tres pestañas:

- **Subida individual** — el TA/AID/UDZ **activo** de la HU seleccionada
  arriba, uno por uno o los N componentes juntos.
- **Subida masiva** — varias HU del sprint (tipo DESPLIEGUE) de una sola vez,
  solo las que estén 100% listas para el ambiente elegido.
- **Carga directa (sin HU)** — para cuando piden subir uno o varios flujos
  puntuales sin pasar por una HU del backlog (ej. a demanda). No corre las
  12 validaciones críticas (dependen de datos de HU que acá no existen) —
  sí chequea el ambiente de cada archivo, y deja su propio registro de
  auditoría en `Backlog_Dealer/_cargas_directas/` (no hay carpeta de HU
  donde guardarlo).

En las tres:

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
  `aws_session_token` solo si son credenciales temporales STS). Se cargan
  desde el panel "Credenciales AWS" arriba de las tres pestañas, sin editar
  el archivo a mano — hay que repetirlo cada vez que la sesión temporal vence.
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

## Roadmap (no implementado todavía)

- **Multiusuario**: hoy es una app de un solo usuario por instancia local.
  La propuesta completa (modelos de despliegue, identidad, manejo del PAT y
  las credenciales AWS, concurrencia de datos) está en
  `docs/PROPUESTA_MULTIUSUARIO.md`.
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
