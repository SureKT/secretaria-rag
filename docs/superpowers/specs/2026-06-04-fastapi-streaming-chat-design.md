# Diseño: Chat con streaming (FastAPI + widget propio)

**Fecha:** 2026-06-04
**Estado:** Aprobado (pendiente review de spec)

## Contexto y objetivo

El bot actual (Typebot → n8n → Qdrant → Ollama) responde correctamente pero:
1. **Lento percibido**: sin streaming, el alumno espera la respuesta completa (5-9 s) antes de ver nada.
2. Arquitectura síncrona (Typebot + n8n webhook) no soporta streaming token a token.

Validado en pruebas directas (`scripts/rag_test.sh`): el pipeline RAG single-call con
`llama3.1:8b` da respuestas exactas en 3.5-9 s. Falta hacerlo **streaming** para que se
sienta instantáneo.

**Objetivo:** servicio nuevo con streaming SSE, widget propio sin login, memoria persistente
e historial, manteniendo la calidad RAG ya lograda.

## Restricción clave: COEXISTENCIA

**No se borra nada del stack actual.** El nuevo servicio se construye EN PARALELO a n8n +
Typebot. Ambas arquitecturas conviven para comparar en caliente. La limpieza (eliminar
Typebot/n8n) se decidirá y ejecutará MÁS ADELANTE, solo si se adopta esta arquitectura.

Implicaciones:
- `secretaria-api` es un servicio **adicional** en docker-compose. Ningún servicio se elimina.
- Widget servido en **puerto 3444** (HTTPS). Typebot sigue intacto en 3443.
- Postgres: **base de datos / esquema nuevo** (`secretaria_chat`). No toca la BD de n8n.
- Qdrant (colección `secretaria`) y Ollama se **comparten** (solo lectura/inferencia, sin conflicto).

## Arquitectura

```
Alumno (navegador)
  │ widget HTML/JS — sin login, token UUID en localStorage
  │ POST /chat  → respuesta SSE (streaming token a token)
  ▼
nginx (puerto 3444 HTTPS, server block nuevo)
  ├─ /              → widget estático
  └─ /chat /history → FastAPI (secretaria-api:8000)
  ▼
FastAPI "secretaria-api"
  1. recibe {message, session_token}
  2. carga historial (Postgres, últimos N turnos)
  3. query history-aware: concat últimos turnos de usuario → texto a embeber
  4. embed (Ollama mxbai-embed-large) → search Qdrant (limit 8)
  5. construye prompt: system grounding + historial + contexto + pregunta
  6. Ollama generate stream=true → emite chunks SSE al navegador
  7. persiste mensaje usuario + respuesta completa (Postgres)
  ▼
Ollama (llama3.1:8b, keep_alive -1)  ·  Qdrant (colección secretaria)  ·  PostgreSQL (secretaria_chat)
```

## Componentes (unidades aisladas)

| Unidad | Responsabilidad | Depende de |
|---|---|---|
| `chat/widget/index.html` + `chat.js` + `style.css` | UI chat, cliente SSE, token localStorage, branding CIPFP | — (estático) |
| `chat/api/main.py` | FastAPI: `POST /chat` (SSE), `GET /history/{token}`, `GET /health` | rag, llm, memory |
| `chat/api/rag.py` | retrieval: embed history-aware + search Qdrant + formato contexto | llm (embed), Qdrant |
| `chat/api/llm.py` | cliente Ollama: embed + generate streaming. Interfaz swappable a OpenAI-compat (vLLM futuro) | Ollama |
| `chat/api/memory.py` | Postgres: cargar historial por token, guardar mensajes, crear conversación | db |
| `chat/api/db.py` | conexión asyncpg + init de esquema | PostgreSQL |
| `chat/api/config.py` | env: modelo, urls, limits, system prompt, num_predict | — |

> Carpeta `chat/` nueva en la raíz del repo. No toca `workflows/`, `scripts/ingest.mjs`,
> `data/` (compartidos) ni los servicios Typebot/n8n.

## Modelo de datos (PostgreSQL, BD `secretaria_chat`)

```sql
CREATE TABLE conversations (
  id            BIGSERIAL PRIMARY KEY,
  session_token TEXT NOT NULL,          -- UUID de localStorage
  created_at    TIMESTAMPTZ DEFAULT now(),
  last_active   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_conv_token ON conversations(session_token);

CREATE TABLE messages (
  id              BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT REFERENCES conversations(id),
  role            TEXT NOT NULL,        -- 'user' | 'assistant'
  content         TEXT NOT NULL,
  created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_msg_conv ON messages(conversation_id);
```

- `session_token`: el navegador genera un UUID la primera vez y lo guarda en localStorage.
  Cada visita reusa el token → el alumno revisita sus chats sin login.
- **Memoria de contexto:** `SELECT ... últimos N mensajes WHERE conversation_id`.
- **Analytics:** queries SQL sobre `messages` (preguntas frecuentes, volumen/día, etc.).
  No requiere identidad real del usuario.

## Flujo por turno (streaming)

1. Widget envía `POST /chat {message, session_token}`.
2. FastAPI resuelve/crea `conversation` por token; carga últimos N mensajes.
3. **Query history-aware**: concatena los últimos 2-3 mensajes de usuario + el actual como
   texto a embeber (resuelve follow-ups tipo "¿y el horario?" sin sujeto).
4. Embed (mxbai) → search Qdrant (limit 8) → formatea contexto (chunks unidos).
5. Construye prompt: system grounding (validado) + historial + contexto + pregunta.
6. `Ollama /api/generate stream=true` → cada token se reenvía como evento SSE al widget.
7. Al terminar, persiste mensaje de usuario + respuesta completa en Postgres; actualiza
   `last_active`.

## Config RAG (ya validada en rag_test.sh)

- Modelo: `llama3.1:8b`, `keep_alive: -1`, `num_predict: 400`
- Embeddings: `mxbai-embed-large:latest`
- Qdrant: colección `secretaria`, `limit: 8`
- System prompt: grounding que usa contexto parcial, sin hedging, no inventa (el validado)
- Query history-aware: concat 2-3 últimos turnos de usuario para el embedding

## Manejo de errores

| Caso | Comportamiento |
|---|---|
| Ollama caído / timeout | emitir chunk SSE de error amable, loguear |
| Sin contexto relevante | el modelo remite a secretaría (vía grounding prompt) |
| Postgres caído | degradar: responder igual (sin memoria), loguear error; no romper el chat |
| Cliente SSE desconecta | abortar generación (cancelar request a Ollama) |
| Embedding falla | error amable, loguear |

## Testing

- `rag.py`: test unitario — retrieval devuelve los chunks esperados para queries clave
  (DAM, becas, óptica). Reusa la lógica de `audit_retrieval.sh`.
- `api`: test integración — `POST /chat` produce un stream no vacío; `GET /history` devuelve
  los mensajes guardados; `GET /health` ok.
- `scripts/rag_test.sh`: se mantiene como regresión de exactitud end-to-end.
- Manual: widget en navegador (streaming visible, historial persiste tras recarga).

## Deploy

- Nuevo servicio `secretaria-api` en `docker-compose.yml` (imagen python, uvicorn, puerto
  interno 8000). `extra_hosts: host.docker.internal` para llegar a Ollama del host.
- nginx: se **reutiliza el contenedor `nginx-viewer` existente** añadiendo un fichero de
  conf nuevo (`nginx/chat.conf`) y mapeando el puerto **3444** (HTTPS, reusa los mismos
  certs). Server block nuevo: `/` → widget estático, `/chat`+`/history` → `secretaria-api:8000`.
  El fichero `nginx/viewer.conf` y el puerto 3443 de Typebot NO se tocan.
- Postgres: el contenedor existente; se crea la BD `secretaria_chat` al iniciar (db.py o init).
- Qdrant/Ollama: compartidos, sin cambios.

## Fuera de alcance v1 (YAGNI)

- Dashboard de analytics (los datos quedan en Postgres; consulta SQL manual de momento).
- vLLM (la interfaz `llm.py` lo deja swappable; se decide según concurrencia real).
- Cuentas de usuario / login.
- OpenWebUI (panel staff; encajaría sobre el mismo backend si se quisiera después).
- Eliminar Typebot/n8n (limpieza diferida hasta decidir arquitectura).

## Decisión pendiente del usuario

Tras construir y comparar B (esta arquitectura) vs A (n8n+Typebot), el usuario decidirá cuál
adoptar. Hasta entonces ambas conviven. Este spec NO implica abandono de A.
