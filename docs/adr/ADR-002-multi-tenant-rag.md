# ADR-002: Multi-tenencia del RAG — un índice con `payload.tenant` + filtro

**Status:** Accepted
**Date:** 2026-06-09
**Deciders:** SureKT (mantenedor), con los dos centros

> Versión pública. Los nombres de los centros se han sustituido por dos ficticios, `norte` y
> `sur`, igual que en el código y en el corpus de ejemplo.

## Contexto

SecretarIA debe servir en producción a **dos centros de FP**. Cada uno tiene su propia
casuística: la oferta de ciclos no coincide (hay familias profesionales que solo imparte uno
de los dos), y las sedes, los correos, los plazos, las tasas y los procedimientos son
propios.

A la vez, **una parte importante del contenido es genérica, autonómica o estatal**, e
idéntica para ambos: acceso a la universidad, becas, homologación de estudios,
convalidaciones y pruebas de acceso.

Fuerzas en juego:
- **Un solo desarrollador y despliegue en semanas:** minimizar piezas y orquestación.
- **Evitar duplicar** el contenido común entre centros (mantenimiento × N).
- **Aislamiento entre centros:** una consulta a un bot no debe devolver datos del otro.
- **Datos volátiles** (plazos, convocatorias, tasas) que caducan cada curso y se
  actualizan por separado.

## Decisión

**Una sola colección Qdrant (`secretaria`) con un campo `payload.tenant` por chunk, y
filtrado por tenant en cada query.** Se adopta el **modelo de contenido "compartido +
overlay por centro" (opción C)** implementado con el **mecanismo de filtrado de la opción
B** (un índice, no colecciones separadas).

- Cada chunk lleva `payload.tenant`:
  - `"norte"` / `"sur"` → contenido específico del centro.
  - `"shared"` → contenido genérico, válido para todos los centros.
- La instancia del bot conoce su centro por la variable de entorno `TENANT` (p. ej.
  `TENANT=sur`).
- Cada búsqueda aplica **siempre** un filtro Qdrant
  `should: [ match(tenant, TENANT), match(tenant, "shared") ]`, de modo que un centro solo
  ve **lo suyo + lo compartido**, nunca lo de otro centro.
- La organización física: `data/<tenant>/*.md` (carpetas `norte/`, `sur/`, `shared/`). El
  pipeline de ingesta deriva el `tenant` del nombre de la carpeta.

## Opciones consideradas

### Opción A: colecciones Qdrant separadas por centro
Una colección por tenant (`secretaria_norte`, `secretaria_sur`).

**Pros:** aislamiento físico total; imposible fuga entre centros por construcción.
**Cons:** el contenido **compartido se duplica** y se reingesta en cada colección
(mantenimiento × N, riesgo de divergencia); duplica configuración y despliegue; no hay
concepto nativo de "shared". Sobredimensionado para 2 tenants con mucho solape.

### Opción B (mecanismo elegido): un índice + `payload.tenant` + filtro
Una colección, cada chunk etiquetado, filtro en la query.

**Pros:** una ingesta, una query, un filtro; patrón estándar de Qdrant; el contenido
`shared` se almacena **una sola vez**; añadir un tercer centro es solo etiquetar datos
nuevos. **Cons:** el aislamiento depende de aplicar el filtro **siempre** (riesgo si se
olvida) → se mitiga centralizando el filtro en `rag.py` y cubriéndolo con tests.

### Opción C-literal: dos espacios de retrieval (compartido + centro) fusionados
Consultar por separado el espacio compartido y el del centro, y **fusionar + re-rankear**
los resultados en el bot.

**Pros:** separación conceptual nítida. **Cons:** duplica las llamadas de búsqueda; añade
lógica de merge, dedupe y re-ranking propia (más código, más puntos de fallo, ranking más
difícil de afinar). La **semántica que aporta (compartido + overlay) se obtiene igual con
la opción B** sin esa orquestación.

> **Resumen de la elección:** se quiere la *taxonomía* de C (shared + overlay) pero la
> *implementación* de B (filtro sobre índice único). C-literal y A añaden complejidad sin
> beneficio para 2 tenants con alto solape de contenido.

## Consecuencias

**Positivas:**
- El contenido común se mantiene una sola vez como `shared`.
- Añadir un centro = crear `data/<nuevo>/`, etiquetar e ingestar; sin tocar el despliegue.
- Despliegue por centro = misma imagen, distinta variable `TENANT`.

**Negativas / a vigilar:**
- **Seguridad y aislamiento:** el filtro por tenant debe aplicarse en **todas** las rutas de
  búsqueda. Está centralizado en `retrieve_context` ([`chat/api/rag.py`](../../chat/api/rag.py))
  y cubierto por pruebas en [`chat/tests/test_rag.py`](../../chat/tests/test_rag.py), que
  comprueban que la búsqueda siempre lleva el filtro y que este solo admite el centro
  actual y `shared`.
- Hace falta un **índice de payload** sobre `tenant` en Qdrant (keyword) para que el filtro
  sea eficiente. Lo crea [`scripts/ingest.mjs`](../../scripts/ingest.mjs).
- Los textos que la ingesta antepone a cada chunk llevaban el nombre de un centro escrito
  a mano. Ahora se parametrizan por centro y se omiten para `shared`.

## Datos volátiles (transversal)

Plazos, convocatorias y tasas caducan cada curso. Se aíslan en ficheros fechados y de baja
densidad (p. ej. `data/<tenant>/convocatorias_2026.md`) para poder actualizarlos sin tocar
el resto del corpus. No es una decisión de tenancy, pero condiciona la organización de
ficheros.

## Implementación

1. `data/` reorganizado en `data/<tenant>/`, con `shared/` para lo común.
2. `ingest.mjs` recorre las subcarpetas, deriva el `tenant` de la carpeta, escribe
   `payload.tenant`, crea el índice keyword y parametriza el nombre del centro.
3. `rag.py` y `config.py`: variable `TENANT` y filtro `should(tenant, shared)` en la búsqueda.
4. Pruebas del filtro en `chat/tests/test_rag.py`.
