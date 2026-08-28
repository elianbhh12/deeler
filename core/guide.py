"""Guía contextual paso a paso que se muestra en el detalle de cada HU."""
from .config import ICON_OK, ICON_ERROR, ICON_WARNING, ICON_NA


def mostrar_guia_tipo(tipo_cambio: str) -> str:
    """Retorna guía paso a paso diferenciada por tipo de cambio"""

    if tipo_cambio == "MODIFICACIÓN":
        return f"""
## GUÍA: Modificación de Caso de Uso Existente

**Impacto: ALTO** — Cambios en procesos que ya operan en producción

---

**Paso 1 — Lee la HU en ADO**
Abre la HU en Azure DevOps y lee la **descripción y comentarios** para entender qué pide el negocio:
- ¿Qué campo, prompt o regla se modifica?
- ¿Se agrega o elimina algo?
- ¿Qué adjuntos relevantes trae la HU?

> **Por qué:** La HU es la fuente de verdad de qué hay que hacer — no el RNF.

---

**Paso 2 — Registra el RNF en el consolidado**
Haz clic en **"Abrir RNF"** y copia los datos de métricas/campos al **Excel consolidado de AID**.
- El RNF **no dice qué hacer** — es el registro de métricas que se lleva al consolidado.

> **Por qué:** El consolidado debe estar actualizado antes de subir a PDN.

---

**Paso 3 — Identifica qué archivos llegaron**
En **"Archivos y adjuntos"** revisa qué componentes adjuntaron en la HU:
- {ICON_OK} Si llegó **TA** — solo modifica el TA según lo que pide la HU
- {ICON_OK} Si llegó **AID** — solo modifica el AID según lo que pide la HU
- {ICON_OK} Si llegó **UDZ** — solo modifica el UDZ según lo que pide la HU
- {ICON_WARNING} Si llegó un **config.json** — ábrelo y confirma a qué componente pertenece antes de usarlo

> **Por qué:** En modificaciones NO se requieren los 3 archivos. Solo se trabaja con lo que la HU envió.

---

**Paso 4 — Revisa si el dashboard detectó algún error**
Si el dashboard encontró algo en los archivos que llegaron, lo verás en **"Validaciones críticas"**.
- Solo aparecen errores en los componentes que sí fueron adjuntados
- Los que no llegaron salen como {ICON_NA} N/A — no los tienes que revisar
- Si hay un {ICON_ERROR} en alguna validación — corrígelo según las instrucciones que aparecen en el detalle

---

**Paso 5 — Verifica retrocompatibilidad**
- ¿El cambio rompe documentos ya procesados en producción?
- ¿Es solo hacia adelante o requiere migración?

---

**Paso 6 — Obtén aprobación y sube a PDN**
- {ICON_OK} HU leída y entendida
- {ICON_OK} RNF registrado en consolidado
- {ICON_OK} Validaciones correctas en los archivos adjuntados
- {ICON_OK} Retrocompatibilidad confirmada

---

**Resumen**
1. HU en ADO — Entiende qué pide el negocio
2. RNF — Regístralo en el consolidado
3. Archivos — Trabaja solo con los que llegaron
4. Dashboard — Revisa si detectó algún error
5. Retrocompatibilidad — Confirma
6. Aprobación — Obtén y sube a PDN
"""

    else:  # DESPLIEGUE
        return f"""
## GUÍA: Despliegue de Caso de Uso Nuevo

**Impacto: CONTROLADO** — Nueva arquitectura, no afecta procesos existentes

---

**Paso 1 — Lee la HU en ADO**
Abre la HU en Azure DevOps y lee la **descripción, comentarios y adjuntos** para entender el caso de uso nuevo:
- ¿Qué tipo documental es?
- ¿Qué proceso de negocio soporta?
- ¿Cuáles son los campos clave a extraer?

> **Por qué:** La HU define qué se despliega y para qué — es el punto de partida.

---

**Paso 2 — Registra el RNF en el consolidado**
Haz clic en **"Abrir RNF"** y copia los datos de métricas/campos al **Excel consolidado de AID**.
- El RNF es el registro de métricas — no define qué hacer, eso lo dice la HU.

---

**Paso 3 — Verifica que los 3 archivos estén presentes**
Un despliegue **requiere obligatoriamente** los 3 componentes:
- **TA** (`ta_*.json`) — Text Analyzer, extracción de campos del documento
- **AID** (`*aid*.json`) — configuración del flujo documental
- **UDZ** (`*udz*.json`) — eventos y seguimiento

> Si alguno falta — estado **INCOMPLETO** — no puedes continuar hasta tenerlos todos.

> {ICON_WARNING} Si hay un **config.json** genérico — ábrelo y confirma que corresponde al componente inferido.

---

**Paso 4 — Revisa las 6 validaciones críticas**
Todas deben estar en {ICON_OK} para poder desplegar:

| Validación | Qué verifica |
|---|---|
| **S3 Path** | AID y UDZ apuntan al mismo bucket (sin `/` final) |
| **Workflow vs ID** | `workflow_name` del AID == `id` del UDZ |
| **Kafka topic** | TA publica en `documentreceivingmanagement.documentuploadedv1` |
| **Coherencia** | `use_case` del AID == `cu_name` del TA |
| **LAST_STEP** | Todos los pasos del AID tienen `LAST_STEP: "False"` |
| **out_zone / copiar** | Si existe `out_zone` — necesita `copiarResultadoBucket: "True"` sin coexistir |

> Si alguna falla — corrígela antes de continuar. **No se puede desplegar con {ICON_ERROR}.**

---

**Paso 5 — Valida el S3 único**
- ¿El `s3_path` es diferente al de otros casos de uso existentes?
- ¿El naming sigue la convención corporativa?

> **Por qué:** Dos procesos con el mismo S3 = datos corruptos.

---

**Paso 6 — Define prueba de humo**
- ¿Qué documento de prueba vas a usar?
- ¿Cómo verificas que la extracción funcionó?
- ¿Cómo verificas que los eventos UDZ se registraron?

---

**Paso 7 — Obtén aprobación y sube a PDN**
- {ICON_OK} HU leída y entendida
- {ICON_OK} RNF registrado en consolidado
- {ICON_OK} Los 3 archivos presentes
- {ICON_OK} Las 6 validaciones en {ICON_OK}
- {ICON_OK} S3 único confirmado
- {ICON_OK} Prueba de humo definida

---

**Resumen**
1. HU en ADO — Entiende el caso de uso
2. RNF — Regístralo en el consolidado
3. 3 archivos — Todos presentes (TA + AID + UDZ)
4. 6 validaciones — Todas en {ICON_OK}
5. S3 único — Confirmado
6. Prueba de humo — Definida
7. Aprobación — Obtén y sube a PDN
"""
