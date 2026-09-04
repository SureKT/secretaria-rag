# SecretarIA — Historial de Decisiones Técnicas

Registro de problemas encontrados, decisiones tomadas y por qué. Útil para no repetir investigaciones.

---

## Búsqueda vectorial en lugar de full-text

**Problema**: Qdrant full-text search no hace accent-folding. La query "Óptica" (con tilde) no matcheaba el texto almacenado "optica" (sin tilde), devolviendo chunks incorrectos (Enfermería en lugar de Óptica).

**Decisión**: Reemplazar búsqueda full-text por búsqueda vectorial (coseno sobre embeddings `mxbai-embed-large`).

**Resultado**: Búsqueda semántica correcta. El embedding captura el significado independientemente de tildes.

**Código en**: `Consultas` jsCode del workflow / `workflows/n8n - SecretarIA.json`

---

## n8n lee de `workflow_history`, no de `workflow_entity.nodes`

**Problema**: Actualizar `workflow_entity.nodes` vía SQL no tenía efecto en las ejecuciones del webhook. El bot seguía usando el código antiguo.

**Causa**: n8n carga los nodos desde `workflow_history` usando `activeVersionId` de `workflow_entity`. La tabla `workflow_entity.nodes` es una copia histórica o de UI, no la que usa el motor en runtime.

**Decisión**: Todos los scripts de despliegue actualizan **ambas tablas** simultáneamente.

**Tablas afectadas**:
- `workflow_entity` (id = `<WORKFLOW_ID>`)
- `workflow_history` (versionId = `<VERSION_ID>`)

---

## `$input` se borra al ejecutar Python via bash `-c "..."`

**Problema**: Al hacer `python3 -c "... $input ..."` en bash, el shell expande `$input` a cadena vacía antes de que Python lo vea.

**Decisión**: Siempre escribir scripts Python a ficheros (`deploy_prompt.py`, etc.) y ejecutarlos como `python3 script.py`.

---

## import `n8n import:workflow` rompe el webhook

**Problema**: Al importar un workflow con `n8n import:workflow --input=file.json`, n8n crea una nueva versión limpia y deja `activeVersionId` a NULL (o a una versión sin webhook registrado). El webhook devuelve 404.

**Solución**: No usar `n8n import:workflow`. En su lugar, actualizar directamente en PostgreSQL via SFTP + psql. Ver `deploy_prompt.py`.

**Si se necesita restaurar**:
```sql
UPDATE workflow_entity
SET "activeVersionId" = '<VERSION_ID>'
WHERE id = '<WORKFLOW_ID>';
```
Luego `docker restart n8n_cerebro`.

---

## host.docker.internal no resuelve a Ollama (v2 workflow)

**Problema**: En el workflow v2, la URL de Ollama era `http://host.docker.internal:11434`. Aunque `extra_hosts` estaba configurado en docker-compose, el container n8n no resolvía ese hostname.

**Decisión**: Usar la IP explícita `http://10.0.0.10:11434` para acceder a Ollama desde cualquier container.

**Afecta**: Workflow v2 y cualquier jsCode que llame a Ollama directamente.

---

## Sistema de prompt demasiado estricto causaba "no tengo ese dato" falsos

**Problema**: El system prompt original decía "Si los fragmentos no contienen EXACTAMENTE el ciclo pedido → di No tengo ese dato". Esto hacía que el modelo descartara chunks relevantes si el primer resultado era de otro ciclo.

**Decisión**: Cambiar a "USA TODO lo que sea relevante; solo di No tengo ese dato si los fragmentos NO mencionan en absoluto el ciclo". Ver `systemMessage` en workflow.

---

## Nombres de ciclos incorrectos en system prompt

**Problema**: El system prompt tenía "Comercio y Marketing (Logística, Ventas, Internacional)" y "Administración y Gestión (Finanzas, Asistencia)". Esos no son nombres de ciclos reales del centro.

**Ciclos reales**:
- Comercio: MP (Marketing y Publicidad), CI (Comercio Internacional), AC (Actividades Comerciales)
- Administración: AF (Administración y Finanzas), GA (Gestión Administrativa)

**Decisión**: Corrección aplicada en `workflows/n8n - SecretarIA.json` y desplegada.

---

## SSH timeout durante benchmark con modelos lentos

**Problema**: Paramiko SSH se desconecta tras ~4-5 min de inactividad (o cuando la respuesta tarda mucho). Afectó especialmente a `gemma4:latest` (~22s por pregunta).

**Solución**: `ssh.get_transport().set_keepalive(20)` — envía paquete keepalive cada 20s.

**Código en**: `scripts/benchmark.py`, función `main()`.

---

## Contaminación de sesiones entre ejecuciones del benchmark

**Problema**: Cada ejecución del benchmark reutilizaba los mismos session IDs (e.g., `bm-mistra-daw_mod`). El nodo `Simple Memory` de n8n acumula historial por `sessionId`, por lo que la 2ª, 3ª, etc. ejecuciones veían el historial de ejecuciones anteriores. Síntomas observados:
- El bot respondía "Ya te he respondido antes..." (GAT)
- Tests fallaban dando respuestas breves tipo "es lo mismo de antes"
- Un test de email pasaba por keyword en respuesta mezclada con memoria antigua

**Solución**: Añadir un sufijo de timestamp de 5 dígitos al prefijo de session ID en cada ejecución (`run_ts = str(int(time.time()))[-5:]`). Cada run del benchmark usa sesiones completamente nuevas.

---

## Hallucinated email address for secretaría

**Problema**: preguntado por el correo de secretaría, el bot devolvió una dirección con el formato correcto pero con el código de centro cambiado — una dirección que no existe. El formato oficial incluye un código numérico de centro, así que una respuesta inventada resulta perfectamente plausible a la vista: es el peor tipo de alucinación, la que no parece una.

**Causa probable**: el vector search devolvió el chunk correcto (contiene el email), pero el LLM regeneró los dígitos en lugar de copiarlos. Alternativa: el chunk correcto no fue el top-1 y se recuperó otro con un código distinto.

**Mitigación**: El test `sec_email` ahora requiere el dominio de correo real del centro en la respuesta, de modo que cualquier respuesta con email inventado falla el test.

**Pendiente**: Comprobar si los chunks de Qdrant tienen contaminación de datos de otros centros.

---

## El ciclo de IA no tiene módulos en los datos

**Problema**: La sección del "Curso de Especialización en Inteligencia Artificial y Big Data" en `familia_informatica.md` solo tiene perfil profesional y salidas. No hay lista de módulos. Preguntando por módulos, el bot correctamente devuelve "no tengo ese dato" o informa del ciclo sin listar asignaturas.

**Decisión**: El test `ia_mod` cambió de "modulos del ciclo de inteligencia artificial" a "informacion sobre el curso de inteligencia artificial y big data", con keywords que validan que el bot devuelva información del perfil/salidas.

**Pendiente**: Añadir los módulos del ciclo IA a `data/familia_informatica.md` cuando se disponga de información oficial.

---

## Modelo de producción: mistral-small3.2:24b

**Por qué no qwen2.5:14b (aunque es 2× más rápido)**:
- `qwen2.5:14b` imprime ocasionalmente sintaxis interna (`_icall_function()`) en la respuesta
- 2 fallos en 21 tests (dam_mod, ctx2) vs 0 fallos de mistral
- Los tiempos de mistral (~11s RAG) son aceptables para un chatbot de secretaría

**Para migrar a qwen2.5:14b en el futuro**: añadir al system prompt `"NUNCA muestres llamadas a funciones ni JSON interno"` (ya existe similar, pero qwen necesita refuerzo explícito).
