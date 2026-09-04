# SecretarIA — Arquitectura del Sistema

## Visión general

SecretarIA es un chatbot RAG (Retrieval-Augmented Generation) para el Centro de FP Ejemplo.  
El usuario pregunta a través de Typebot → n8n orquesta la respuesta → Ollama genera el texto final.

```
Usuario (Typebot)
      │ POST /webhook/typebot-agent
      ▼
  n8n (AI Agent)
      │
      ├── [sin tool] → respuesta directa del LLM (saludos, familias profesionales)
      │
      └── [tool: Consultas] ─────────────────────────────────────────┐
                                                                      │
              jsCode en n8n TaskRunner                                │
                    │                                                 │
                    ├─ embed query → Ollama /api/embeddings           │
                    │   model: mxbai-embed-large:latest               │
                    │   host: 10.0.0.10:11434 (nativo, no Docker)  │
                    │                                                 │
                    └─ vector search → Qdrant :6333                  │
                        collection: secretaria                        │
                        top-6 chunks by cosine similarity            │
                                                                      │
              fragmentos relevantes ◄────────────────────────────────┘
                    │
                    ▼
          LLM (Ollama Chat Model)
          model: mistral-small3.2:24b
          host: 10.0.0.10:11434
                    │
                    ▼
          Respuesta final → Typebot
```

## Componentes de infraestructura

| Componente         | Tipo         | Host/Puerto              | Notas                                      |
|--------------------|--------------|--------------------------|---------------------------------------------|
| Ollama             | Nativo (DGX) | 10.0.0.10:11434        | NO está en Docker; acceso directo por IP   |
| n8n (cerebro)      | Docker        | localhost:5678           | Container: `n8n_cerebro`                   |
| Qdrant             | Docker        | qdrant:6333 (interno)    | Nombre DNS interno del compose             |
| PostgreSQL         | Docker        | postgres_db              | BD de n8n: `SecretarIA`                    |
| Typebot (builder)  | Docker        | localhost:3002           | Puerto cambiado de 3000 a 3002             |
| nginx              | Docker/host   | :80/:443                 | Proxy para webhook y viewer                |

## Workflow n8n (v1 — producción)

- **ID**: `<WORKFLOW_ID>`
- **versionId activa**: `<VERSION_ID>`
- **Webhook path**: `POST /webhook/typebot-agent`
- **Body**: `{ "pregunta": "...", "sessionId": "..." }`
- **Response**: `{ "output": "..." }`

### Nodos principales

| Nodo              | Tipo                  | Función                                         |
|-------------------|-----------------------|-------------------------------------------------|
| Webhook           | Trigger               | Entrada HTTP POST                               |
| Edit Fields       | Set                   | Extrae `pregunta` y `sessionId` del body        |
| AI Agent          | LangChain Agent       | Orquesta LLM + herramienta                      |
| Simple Memory     | Buffer Window Memory  | Historial de conversación por `sessionId`       |
| Ollama Chat Model | LLM                   | `mistral-small3.2:24b` en Ollama                |
| Consultas         | Tool (jsCode)         | Búsqueda semántica vectorial en Qdrant          |
| Respond to Webhook| Output                | Devuelve JSON con `output`                      |

## Base de datos vectorial (Qdrant)

- **Colección**: `secretaria`
- **Dimensiones**: 1024 (mxbai-embed-large)
- **Distancia**: Coseno
- **Chunks**: fragmentos de ~500 palabras extraídos de los `.md` de `data/`
- **Sin índice full-text** (se eliminó porque no admite accent-folding)

## Archivos de datos (`data/`)

| Archivo                            | Contenido                                          |
|------------------------------------|----------------------------------------------------|
| `familia_informatica.md`           | SMR, DAW, DAM, ASIR, IA, Ciberseguridad           |
| `familia_sanidad.md`               | Enfermería (CAE), Laboratorio, Óptica, Prótesis   |
| `familia_administracion.md`        | Gestión Administrativa (GA), Administración y Finanzas (AF) |
| `familia_comercio_y_marketing.md`  | Marketing y Publicidad (MP), Comercio Internacional (CI), Actividades Comerciales (AC) |
| `familia_turismo.md`               | Gestión de Alojamientos Turísticos (GAT)          |
| `admision_matricula_2025_26.md`    | Calendarios y documentación de admisión           |
| `becas_y_ayudas_2025_26.md`        | Becas MEC y GVA                                   |
| `tramites_y_horarios.md`           | Horarios de secretaría, trámites académicos       |
| `logistica_sedes_y_servicios.md`   | Sedes, servicios del centro                       |
| `preguntas_frecuentes_y_casos_especiales.md` | Convalidaciones, FCT, acceso sin título |

## Modelos Ollama disponibles en el servidor

| Modelo                  | Uso               | Notas                                          |
|-------------------------|-------------------|------------------------------------------------|
| `mistral-small3.2:24b`  | Chat (producción) | Mejor calidad, ~11s RAG                        |
| `qwen2.5:14b`           | Chat (candidato)  | 2× más rápido (~5.5s RAG), 90% calidad        |
| `qwen2.5:7b`            | Chat (descartado) | Muy rápido pero alucinaciones frecuentes       |
| `gemma4:latest`         | Chat (descartado) | Muy lento (~20s), tiempos de SSH inaceptables |
| `mxbai-embed-large`     | Embeddings        | 1024 dims, único modelo de embeddings en uso  |
