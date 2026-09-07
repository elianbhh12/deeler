# Propuesta: llevar la herramienta a multiusuario

## 0. Contexto y objetivo

Hoy la app corre **mono-usuario, mono-máquina**: cada persona la ejecuta con `run.bat` en su propio equipo, con su propio `.env` (su `ADO_PAT`, su `ROOT_FOLDER` local tipo `C:\Backlog_Dealer`, sus credenciales AWS locales). Nada se comparte entre analistas.

El pedido es pasar a un esquema donde:
- Varios analistas usan la herramienta **al mismo tiempo**.
- Todos ven **el mismo backlog** (mismas HU descargadas, mismo Excel consolidado, mismo estado de validación/PDN).
- La app y/o los datos viven en una **ruta de red compartida**, no en `C:\` de cada uno.
- Nadie necesita su propio token de Azure DevOps para poder descargar HU — o al menos, el mecanismo de token no debe ser "cada uno pega el suyo a mano en un `.env` local".
- Ninguna ruta queda "fija por usuario" (nada de `C:\Users\<nombre>\...` ni de un `.env` distinto por máquina) — todo apunta a una configuración general, única, compartida.

Esto es un cambio de arquitectura, no un ajuste cosmético. El resto del documento explica **qué se rompe si solo se mueve la carpeta a la red sin más cambios**, y después compara 3 formas de resolverlo, pensando en que están en un **entorno bancario** (VPN corporativa, políticas de credenciales, sin poder instalar libremente infraestructura cloud pública).

---

## 1. Qué se rompe si solo "se pone en una carpeta de red"

Es tentador pensar que la solución es: mover `ROOT_FOLDER` a un `\\servidor\share\Backlog_Dealer` y que cada quien siga corriendo `streamlit run` desde su propia PC apuntando ahí. Es el cambio de menor esfuerzo, pero trae problemas reales:

| Problema | Por qué pasa | Impacto concreto |
|---|---|---|
| **Colisión de escritura en JSON** | `analisis_tecnico.json` se reescribe completo en cada análisis, click de "Marcar QA", subida a AWS, etc. Sin locking, dos analistas tocando la misma HU casi al mismo tiempo pueden pisarse el archivo (uno pierde su cambio). | Se pierde trazabilidad ("¿quién aprobó esto?") sin que nadie note el pisado. |
| **Excel consolidado bloqueado** | `Consolidado_Backlog.xlsx` se regenera automáticamente tras cada acción (`_excel_pending`). Si alguien lo tiene **abierto en Excel** (típico: alguien lo dejó abierto para mirarlo), Windows bloquea el archivo y la escritura falla. | Falla silenciosa (ya lo dejamos como `st.toast` de error, pero sigue fallando) — el consolidado queda desactualizado. |
| **Token de ADO por persona** | `ADO_PAT` es personal e intransferible por política normal de Azure DevOps (y de cualquier banco). Si se comparte un PAT en un `.env` de red, **todas las descargas quedan atribuidas a esa persona** en la auditoría de ADO, y si esa persona se va o rota su clave, la app entera deja de funcionar para todos. | Riesgo de compliance + punto único de falla. |
| **Credenciales AWS compartidas** | Mismo problema que el PAT: `aws_credentials.json` es de una identidad. Si es compartido, toda subida a QA/PDN queda "hecha por" esa identidad ante AWS, aunque la app registre `_aws_por` con el nombre real del analista (ver `core.utils.obtener_usuario_actual`) — son dos sistemas de auditoría que dejan de coincidir. | Trazabilidad rota entre "quién lo hizo en la app" y "quién lo hizo según AWS". |
| **Identidad del usuario** | `obtener_usuario_actual()` usa `os.getlogin()` (usuario de Windows de la sesión). Esto solo es confiable si **cada quien corre su propio proceso de Streamlit en su propia sesión de Windows**. | Deja de servir apenas se centraliza en un solo servidor (ver más abajo). |
| **Rutas de red y permisos NTFS/SMB** | Un share de red necesita permisos de lectura/escritura para todo el grupo, y Windows puede tener locks más agresivos sobre archivos en SMB que en disco local (más lento, más margen para errores intermitentes de "archivo en uso"). | Errores intermitentes difíciles de reproducir. |

Conclusión: **mover la carpeta sola no alcanza**. Hace falta decidir (a) dónde corre el proceso de Streamlit, (b) cómo se identifica a cada usuario, (c) cómo se maneja el token de ADO y las credenciales AWS, y (d) cómo se evita que dos escrituras simultáneas se pisen.

---

## 2. Dos modelos de despliegue posibles

### Modelo A — "Red compartida, N procesos" (lo que sugiere el pedido tal cual)

Cada analista sigue corriendo su propio `streamlit run` (vía `run.bat`), pero:
- El **código** vive en una ruta de red compartida (todos corren la misma versión, sin copiar el proyecto a cada PC).
- El **`ROOT_FOLDER`** (HU descargadas, análisis, Excel) apunta a una carpeta de red común, no a `C:\`.
- La config (`.env`) deja de tener valores por-persona: se centraliza (ver sección 4).

**Ventajas:** no requiere pedirle a IT un servidor nuevo ni tocar la red corporativa más de lo que ya está (todos ya tienen acceso VPN/LAN al share). Cero curva de aprendizaje para el usuario (sigue siendo "doble click a `run.bat`").

**Desventajas:** cada analista sigue teniendo **su propio proceso Python** local — o sea, N procesos leyendo y escribiendo el mismo storage al mismo tiempo, sin ningún árbitro central. Todos los problemas de la sección 1 (colisión de JSON, Excel bloqueado) siguen existiendo tal cual, aunque se puedan mitigar (sección 5). Es el modelo con más trabajo de "parcheo" para que la concurrencia no rompa datos.

### Modelo B — "Servidor único, todos por navegador" (recomendado)

Un solo proceso de Streamlit corre en una máquina del banco (un servidor Windows/Linux ya existente, o una VM chica) y todos los analistas entran **por navegador** a esa URL interna, sin instalar nada localmente.

**Ventajas:**
- Un solo proceso = un solo punto de escritura → mucho más fácil de serializar correctamente (una cola/lock interno resuelve el 100% de las colisiones, no un 80%).
- Un solo lugar donde vive el `ADO_PAT`/credenciales AWS — nunca viajan a la PC de cada analista, nunca están en un `.env` que alguien pueda copiar sin querer.
- Es el modelo estándar para "herramienta interna" en cualquier banco: URL interna, sin instalación, funciona igual desde cualquier PC de la red.
- Facilita conectar autenticación corporativa real (SSO/AD) más adelante.

**Desventajas:** requiere que IT provisione (o preste) una máquina donde correr el servicio 24/7, y typically correrlo como servicio de Windows (o bajo IIS/nginx como proxy) en vez de una ventana de consola abierta. Es "pedir infraestructura", no solo cambiar una ruta.

**Mi recomendación:** empezar con **Modelo A** si conseguir un servidor va a tomar semanas/meses de trámite interno (para no bloquear el objetivo de "multiusuario ya"), pero dejar dicho explícitamente que es una solución de transición, y migrar a **Modelo B** en cuanto haya una máquina disponible. Los cambios de código de las secciones 3-6 sirven para **ambos modelos** (no se tiran si después migran a B).

---

## 3. Identidad de usuario (quién es quién)

Hoy: `os.getlogin()`. Deja de alcanzar en Modelo B (todos entran como el usuario de servicio que corre Streamlit) y se vuelve frágil en Modelo A si alguien corre la app con una cuenta de servicio o RDP compartido.

Opciones, de menor a mayor esfuerzo:

1. **Login manual simple** (mínimo esfuerzo): al abrir la app, un campo "¿Quién sos?" (nombre/usuario), guardado en `st.session_state` para esa sesión de navegador. No hay contraseña, es solo etiqueta para trazabilidad — parecido a lo que ya hace `obtener_usuario_actual()` hoy, pero explícito y no atado a Windows.
   - Riesgo: cualquiera puede tipear el nombre de otro. Aceptable si el objetivo es solo trazabilidad interna, no control de acceso.
2. **Seguir usando `os.getlogin()` pero solo en Modelo A**: sigue funcionando porque cada quien corre su propio proceso. Es gratis (cero cambios), pero es la razón principal para no ir directo a Modelo B sin resolver esto antes.
3. **Autenticación corporativa real (recomendado a mediano plazo)**: en un banco esto normalmente ya existe como capacidad de infraestructura:
   - **IIS con Autenticación de Windows Integrada (Kerberos/NTLM)** como reverse proxy delante de Streamlit → el proxy inyecta el usuario de AD autenticado en un header (`REMOTE_USER`), la app lo lee. Cero fricción para el usuario (ya está logueado en su PC de dominio).
   - **Azure AD / Entra ID (SSO/OAuth2)** si el banco ya usa Entra ID para otras apps internas — un poco más de configuración pero es el estándar moderno y da MFA gratis.
   - Cualquiera de las dos resuelve identidad **y** de paso resuelve control de acceso (solo gente del dominio/grupo correspondiente entra).

---

## 4. El token de Azure DevOps — la parte más delicada

Este es el punto que hay que decidir con más cuidado por el lado de compliance del banco. Opciones:

### Opción 1 — PAT de cuenta de servicio ("service account")
Se crea en ADO un usuario "robot" (ej. `svc-pia-backlog`) con permisos de **solo lectura** sobre el proyecto/área (alcanza con leer Work Items + descargar adjuntos, no hace falta nada más). Su PAT se genera con:
- **Scope mínimo**: "Work Items (Read)" únicamente.
- **Expiración corta** (90 días típico) con proceso documentado de renovación.
- Se guarda en un solo lugar protegido (no en el `.env` del repo compartido en texto plano si se puede evitar): idealmente **Azure Key Vault** si el banco ya lo usa, o al menos un archivo con ACL de NTFS restringido a la cuenta de servicio que corre Streamlit (no legible por los analistas).

**Pro:** un solo punto de rotación, no depende de que una persona se vaya de la empresa. Es lo más simple de operar.
**Contra:** en el log de auditoría de ADO, toda descarga aparece hecha por "svc-pia-backlog", no por el analista real — se pierde granularidad de auditoría del lado de ADO (pero la app ya registra `analizado_por` con el usuario real, así que la trazabilidad interna de la herramienta no se pierde, solo la de ADO).

### Opción 2 — Cada analista ingresa su propio PAT por sesión
Al entrar a la app (o solo la primera vez que usa "Descargar HU"), el usuario pega su propio PAT personal en un campo `type="password"`, que se guarda **solo en memoria de esa sesión** (nunca a disco). Cada descarga queda atribuida a la persona real en ADO.

**Pro:** auditoría perfecta en ambos lados (app y ADO), sin credenciales compartidas nunca.
**Contra:** fricción — cada analista tiene que saber crear un PAT en ADO (hay que documentarlo/dar instructivo), y si la sesión se cierra hay que volver a pegarlo. En Modelo A (proceso local) esto es más natural porque de última cada uno ya tiene su `.env`; en Modelo B (servidor compartido) es más importante todavía no persistirlo nunca a disco del servidor.

### Opción 3 — App registrada en Entra ID con permisos delegados a ADO (OAuth)
El usuario se autentica una vez con su cuenta corporativa (SSO) y la app pide un token OAuth con scope hacia Azure DevOps en su nombre (delegated permissions). Es el modelo "más correcto" en teoría — no hay PAT de nadie, el token es de corta vida y se renueva solo.

**Pro:** el más seguro y auditable de los tres, sin gestión manual de PATs.
**Contra:** requiere registrar una App en Entra ID (aprobación de seguridad/IT), y bastante más trabajo de implementación (flujo OAuth completo). No es "para ya".

**Mi recomendación:** arrancar con **Opción 1** (PAT de servicio, solo lectura, en Key Vault o archivo con ACL restringida) para no bloquear el proyecto, dejando la puerta abierta a migrar a Opción 3 si el banco ya tiene el hábito de registrar Apps en Entra ID para herramientas internas. Opción 2 es la alternativa si el área de seguridad no permite crear cuentas de servicio para ADO.

---

## 5. Credenciales AWS — mismo dilema, misma lógica

Ya usan credenciales STS temporales (`aws_credentials.json` con `session_token`), lo cual ya es mejor práctica que una access key permanente. La pregunta multiusuario es la misma que con el PAT:

- **Opción recomendada:** un **rol IAM de servicio** (no personal) con permisos acotados a `PutItem`/`GetItem` únicamente sobre las 6 tablas DynamoDB que ya usa la app (`AWS_TABLAS` en `core/config.py`), asumido vía STS por el servidor. Se renueva automáticamente (hay librerías de boto3 que refrescan solas, o un cronjob que regenera el JSON cada X horas si las credenciales STS vienen de un proceso externo del banco).
- Igual que con ADO, la auditoría "quién subió qué" ya la resuelve la app (`{tipo}_aws_por`, ver `ui/aws_console.py::_persistir_subida_aws`) independientemente de qué credencial de AWS se use para la llamada — así que compartir un rol de servicio acá es más aceptable que en ADO (no se pierde trazabilidad de negocio, solo la traza de IAM interna de AWS, que para este caso de uso es secundaria).

---

## 6. Concurrencia y consistencia de datos — la parte técnica

Independientemente del modelo de despliegue elegido, hace falta resolver el problema de "dos escrituras al mismo tiempo". Tres niveles de esfuerzo, se puede ir escalando:

### Nivel 1 (mínimo, rápido de meter)
- **File locking** en las escrituras a `analisis_tecnico.json` y `Consolidado_Backlog.xlsx` con la librería `filelock` (multiplataforma, funciona sobre share de red). Si el archivo está bloqueado, se reintenta un par de veces con backoff corto antes de avisar error — en vez de fallar directo si alguien lo tiene abierto en Excel.
- **Escritura atómica**: escribir a un archivo temporal y hacer `os.replace()` al final (rename atómico), en vez de escribir directo sobre el archivo final — evita que una escritura interrumpida a mitad de camino (ej. se cae la red del share) deje un JSON corrupto e ilegible.
- Esto ya cubre el 90% del riesgo real, porque en la práctica dos analistas rara vez tocan la **misma HU** en el mismo segundo (el conflicto es raro, solo hay que evitar que cuando pasa, corrompa datos en vez de solo pisar el último valor).

### Nivel 2 (si el equipo crece o el conflicto se vuelve frecuente)
- Mover el "Excel consolidado" de ser un archivo que se regenera completo tras cada acción, a generarse **solo bajo demanda** (botón "Generar Excel ahora") o en un job programado cada N minutos — reduce drásticamente la frecuencia de escritura y por lo tanto la chance de colisión con alguien que lo tiene abierto.
- Agregar un `analizando_por` / lock lógico visible en la UI: si HU-123 la está analizando otra persona ahora mismo, mostrarlo (evita el conflicto en vez de solo resolverlo técnicamente).

### Nivel 3 (robusto, más trabajo — para cuando esto deje de ser una herramienta de equipo chico)
- Migrar el storage de "un JSON por HU + un Excel" a una **base de datos real** (SQLite con modo WAL si quieren algo sin infraestructura nueva, o SQL Server si el banco ya tiene uno disponible para este tipo de herramientas internas). Esto elimina el problema de raíz: las bases de datos ya resuelven concurrencia, transacciones y consistencia por diseño. El "Excel consolidado" pasaría a ser una vista/export generada desde la DB, no la fuente de verdad.
- Es la opción más sólida a largo plazo, pero es la que más cambios de código implica (`core/analysis.py` y `core/reports.py` dejan de leer/escribir archivos directamente).

**Mi recomendación:** implementar **Nivel 1 ya** (bajo costo, alto impacto) sin importar qué modelo de despliegue elijan. Nivel 2 si notan fricción real en el uso diario. Nivel 3 solo si el equipo/volumen crece bastante (por ejemplo, si pasan de un puñado de analistas a decenas, o de un sprint a la vez a varios sprints en paralelo).

---

## 7. Rutas "no fijas por usuario" — cómo generalizar la config

Hoy cada instalación tiene su propio `.env` con valores propios de esa persona/máquina. Para que sea realmente "una sola config general":

1. **Un solo `.env` compartido**, ubicado junto al código en la ruta de red (Modelo A) o en el servidor (Modelo B) — no uno por persona. Contendría: `ADO_ORG/PROJECT/TEAM/AREA` (institucionales, no personales), `ROOT_FOLDER` apuntando siempre a la ruta de red común, y el PAT de servicio (sección 4) en vez de uno personal.
2. **`ROOT_FOLDER` deja de tener sentido como variable por-persona** — pasa a ser una única ruta UNC (`\\servidor\share\PIA_Backlog`) igual para todos. El código de `core/config.py` no necesita cambios para esto (ya lo lee de `.env`), solo cambia el **valor**.
3. **`AWS_CRED_FILE`** igual: una sola ubicación compartida (protegida con ACL) en vez de un archivo por persona en cada `C:\`.
4. Nada de lo anterior requiere tocar `core/utils.py::safe_name` ni la lógica de armado de carpetas por HU (`{id}-{título}`) — esa parte ya es agnóstica de usuario, el problema nunca estuvo ahí.

En otras palabras: el código de `core/config.py` **ya está preparado** para esto (lee todo de variables de entorno, nada hardcodeado por persona) — el cambio real es operativo: un `.env` único y bien resguardado, no una fórmula de "cada quien el suyo".

---

## 8. Checklist de seguridad para entorno bancario

Antes de dar esto por "listo para producción interna":

- [ ] El PAT/credencial de servicio tiene el **scope mínimo posible** (solo lectura de Work Items; nada de permisos de escritura/admin que no se usan).
- [ ] El archivo de config con el PAT/credenciales AWS **no es legible por los analistas** (ACL de NTFS restringida a la cuenta que corre el proceso), y no está en ningún repositorio.
- [ ] Hay un **responsable y un proceso documentado de rotación** del PAT y de las credenciales AWS (quién lo renueva, cada cuánto, qué hacer si se filtra).
- [ ] Si van con Modelo B (servidor único), el tráfico entre navegador y servidor va sobre **HTTPS interno**, no HTTP plano, aunque sea red interna.
- [ ] Los `except Exception` que hoy silencian errores (ya corregido uno en `dashboard.py`) no esconden fallos de escritura que puedan hacer perder trazabilidad — revisar que cualquier error de concurrencia quede visible al usuario, no tragado.
- [ ] Definir qué pasa si el share de red no está disponible (VPN caída, mantenimiento): la app debería fallar con un mensaje claro, no con un traceback crudo.

---

## 9. Resumen de la propuesta (recomendación concreta)

Para arrancar sin bloquearse en trámites de infraestructura, pero dejando el camino libre a algo más sólido después:

1. **Ahora (semanas):** Modelo A (código y `ROOT_FOLDER` en un share de red único) + Nivel 1 de concurrencia (file locking + escritura atómica) + PAT de servicio de solo-lectura guardado con ACL restringida + credenciales AWS de rol de servicio.
2. **Después (cuando haya servidor disponible):** migrar a Modelo B (servidor único, acceso por navegador) sin tocar la lógica de negocio — es un cambio de *cómo se lanza el proceso*, no de qué hace. Sumar autenticación real (IIS+Kerberos o Entra ID) en ese momento, que es cuando realmente hace falta (con Modelo A, `os.getlogin()` todavía sirve).
3. **Más adelante, si el volumen lo justifica:** Nivel 3 (base de datos real en vez de JSON+Excel).

Esto evita "hacer todo de una" (que sería mucho tiempo de desarrollo antes de tener algo usable) y evita también "solo mover la carpeta" (que rompe trazabilidad y arriesga corrupción de datos). Cada paso es incremental y no se tira el trabajo del paso anterior.
