# FastAPI Streaming Chat — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a streaming (SSE) chat service with a custom login-less widget, persistent history, and the already-validated RAG pipeline — running ALONGSIDE the existing n8n/Typebot stack (no removals).

**Architecture:** A FastAPI service (`chat/api`) embeds the query (history-aware), searches Qdrant, and streams tokens from Ollama (`llama3.1:8b`) to a static HTML/JS widget via Server-Sent Events. Conversations persist in a new PostgreSQL database (`secretaria_chat`) keyed by a browser-localStorage UUID. Served on a new nginx port 3444; Typebot (3443) and n8n untouched.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, httpx (async Ollama/Qdrant client), asyncpg (PostgreSQL), pytest + pytest-asyncio, vanilla HTML/CSS/JS (no framework), Docker Compose, nginx.

---

## File Structure

All new code lives under `chat/`. Nothing in `workflows/`, `scripts/`, `data/`, or existing services is modified except `docker-compose.yml` (add one service + port) and a new `nginx/chat.conf`.

```
chat/
├── api/
│   ├── __init__.py
│   ├── config.py        # env vars, system prompt, constants
│   ├── llm.py           # Ollama client: embed() + generate_stream()
│   ├── rag.py           # history-aware query build + Qdrant search + context format
│   ├── db.py            # asyncpg pool + schema init
│   ├── memory.py        # load history, save messages, get/create conversation
│   └── main.py          # FastAPI app: /chat (SSE), /history, /health
├── widget/
│   ├── index.html       # chat UI
│   ├── chat.js          # SSE client, localStorage token, render
│   └── style.css        # CIPFP branding
├── tests/
│   ├── __init__.py
│   ├── conftest.py      # fixtures (httpx mock, db)
│   ├── test_config.py
│   ├── test_llm.py
│   ├── test_rag.py
│   ├── test_memory.py
│   └── test_main.py
├── requirements.txt
├── Dockerfile
└── .env.example
nginx/chat.conf          # new server block, port 444 internal -> 3444 host
docker-compose.yml       # MODIFY: add secretaria-api service + 3444 mapping
```

**Unit boundaries:**
- `config.py` — pure constants/env. No I/O. Depends on nothing.
- `llm.py` — only talks to Ollama. Input/output: strings, async generators. No DB, no Qdrant.
- `rag.py` — orchestrates embed (via llm) + Qdrant HTTP. Returns formatted context string.
- `db.py` — connection pool + schema. No business logic.
- `memory.py` — conversation/message CRUD. Depends on db only.
- `main.py` — HTTP layer. Wires rag + llm + memory. No business logic inline.

---

## Task 1: Project scaffold + config

**Files:**
- Create: `chat/api/__init__.py` (empty)
- Create: `chat/tests/__init__.py` (empty)
- Create: `chat/requirements.txt`
- Create: `chat/.env.example`
- Create: `chat/api/config.py`
- Create: `chat/tests/conftest.py`
- Create: `chat/tests/test_config.py`

- [ ] **Step 1: Create requirements.txt**

```
fastapi==0.115.5
uvicorn[standard]==0.32.1
httpx==0.27.2
asyncpg==0.30.0
pytest==8.3.4
pytest-asyncio==0.24.0
```

- [ ] **Step 2: Create .env.example**

```
OLLAMA_URL=http://host.docker.internal:11434
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=secretaria
EMBED_MODEL=mxbai-embed-large:latest
LLM_MODEL=llama3.1:8b
RETRIEVAL_LIMIT=8
NUM_PREDICT=400
HISTORY_TURNS=6
EMBED_QUERY_TURNS=3
DATABASE_URL=postgresql://postgres:CHANGEME@postgres:5432/secretaria_chat
```

- [ ] **Step 3: Write the failing test**

`chat/tests/test_config.py`:

```python
from api import config


def test_defaults_present():
    assert config.LLM_MODEL  # non-empty
    assert config.EMBED_MODEL
    assert config.RETRIEVAL_LIMIT == 8
    assert config.HISTORY_TURNS == 6
    assert config.EMBED_QUERY_TURNS == 3
    assert "SecretarIABot" in config.SYSTEM_PROMPT
    assert "secretar" in config.SYSTEM_PROMPT.lower()


def test_env_override(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_LIMIT", "5")
    import importlib
    importlib.reload(config)
    assert config.RETRIEVAL_LIMIT == 5
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd chat && python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.config'`

- [ ] **Step 5: Write minimal implementation**

`chat/api/config.py`:

```python
import os

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "secretaria")
EMBED_MODEL = os.getenv("EMBED_MODEL", "mxbai-embed-large:latest")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1:8b")
RETRIEVAL_LIMIT = int(os.getenv("RETRIEVAL_LIMIT", "8"))
NUM_PREDICT = int(os.getenv("NUM_PREDICT", "400"))
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "6"))
EMBED_QUERY_TURNS = int(os.getenv("EMBED_QUERY_TURNS", "3"))
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/secretaria_chat"
)

SYSTEM_PROMPT = (
    "Eres SecretarIABot, asistente del Centro de FP Ejemplo. Usa la informacion RELEVANTE del "
    "CONTEXTO para responder, aunque haya fragmentos no relacionados (ignoralos). "
    "No inventes datos que no esten en el contexto. Solo remite a secretaria si NO hay "
    "NADA relevante. Responde directo, breve y en español. NO empieces con disculpas ni "
    'con frases como "no se menciona" o "segun la informacion" si vas a dar datos: '
    "responde la informacion directamente."
)
```

- [ ] **Step 6: Create empty package + conftest files**

`chat/api/__init__.py`: empty.
`chat/tests/__init__.py`: empty.
`chat/tests/conftest.py`:

```python
import sys
from pathlib import Path

# make `api` importable from chat/ root when running pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd chat && python -m pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: Commit**

```bash
git add chat/api/__init__.py chat/tests/__init__.py chat/tests/conftest.py chat/tests/test_config.py chat/api/config.py chat/requirements.txt chat/.env.example
git commit -m "feat(chat): scaffold + config for streaming chat service"
```

---

## Task 2: LLM client (Ollama embed + streaming generate)

**Files:**
- Create: `chat/api/llm.py`
- Test: `chat/tests/test_llm.py`

- [ ] **Step 1: Write the failing test**

`chat/tests/test_llm.py`:

```python
import json
import pytest
import httpx
from api import llm


@pytest.mark.asyncio
async def test_embed_returns_vector(monkeypatch):
    async def fake_post(self, url, json=None, **kw):
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    vec = await llm.embed("hola")
    assert vec == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_generate_stream_yields_tokens(monkeypatch):
    lines = [
        json.dumps({"response": "Hola", "done": False}),
        json.dumps({"response": " mundo", "done": False}),
        json.dumps({"response": "", "done": True}),
    ]

    class FakeStream:
        def __init__(self): self.status_code = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def aiter_lines(self):
            for ln in lines:
                yield ln

    def fake_stream(self, method, url, json=None, **kw):
        return FakeStream()
    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)

    out = []
    async for tok in llm.generate_stream("sys", "prompt"):
        out.append(tok)
    assert out == ["Hola", " mundo"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd chat && python -m pytest tests/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.llm'`

- [ ] **Step 3: Write minimal implementation**

`chat/api/llm.py`:

```python
import json
from typing import AsyncIterator
import httpx
from api import config


async def embed(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{config.OLLAMA_URL}/api/embeddings",
            json={"model": config.EMBED_MODEL, "prompt": text},
        )
        r.raise_for_status()
        return r.json()["embedding"]


async def generate_stream(system: str, prompt: str) -> AsyncIterator[str]:
    payload = {
        "model": config.LLM_MODEL,
        "system": system,
        "prompt": prompt,
        "stream": True,
        "keep_alive": -1,
        "options": {"num_predict": config.NUM_PREDICT},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST", f"{config.OLLAMA_URL}/api/generate", json=payload
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                tok = obj.get("response", "")
                if tok:
                    yield tok
                if obj.get("done"):
                    break
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd chat && python -m pytest tests/test_llm.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add chat/api/llm.py chat/tests/test_llm.py
git commit -m "feat(chat): Ollama client with embed + streaming generate"
```

---

## Task 3: RAG (history-aware query + Qdrant search + context format)

**Files:**
- Create: `chat/api/rag.py`
- Test: `chat/tests/test_rag.py`

- [ ] **Step 1: Write the failing test**

`chat/tests/test_rag.py`:

```python
import pytest
import httpx
from api import rag


def test_build_embed_query_concats_last_user_turns():
    history = [
        {"role": "user", "content": "que modulos tiene DAM"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "y el horario?"},
    ]
    q = rag.build_embed_query(history, "y la sede?", turns=3)
    # last user turns + current, assistant excluded
    assert "que modulos tiene DAM" in q
    assert "y el horario?" in q
    assert "y la sede?" in q
    assert "..." not in q


def test_build_embed_query_no_history():
    q = rag.build_embed_query([], "que becas hay", turns=3)
    assert q == "que becas hay"


@pytest.mark.asyncio
async def test_search_returns_formatted_context(monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]
    monkeypatch.setattr(rag.llm, "embed", fake_embed)

    async def fake_post(self, url, json=None, **kw):
        return httpx.Response(200, json={"result": [
            {"payload": {"content": "DAM tiene Programacion"}},
            {"payload": {"content": "Bases de datos"}},
        ]})
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    ctx = await rag.retrieve_context("que modulos DAM", [])
    assert "DAM tiene Programacion" in ctx
    assert "Bases de datos" in ctx


@pytest.mark.asyncio
async def test_search_empty_returns_empty_string(monkeypatch):
    async def fake_embed(text):
        return [0.1]
    monkeypatch.setattr(rag.llm, "embed", fake_embed)

    async def fake_post(self, url, json=None, **kw):
        return httpx.Response(200, json={"result": []})
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    ctx = await rag.retrieve_context("xyz", [])
    assert ctx == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd chat && python -m pytest tests/test_rag.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.rag'`

- [ ] **Step 3: Write minimal implementation**

`chat/api/rag.py`:

```python
import httpx
from api import config, llm


def build_embed_query(history: list[dict], message: str, turns: int) -> str:
    """Concat the last `turns` user messages + current message for a richer
    embedding that survives context-less follow-ups ("y el horario?")."""
    user_msgs = [m["content"] for m in history if m["role"] == "user"]
    recent = user_msgs[-(turns - 1):] if turns > 1 else []
    parts = recent + [message]
    return " ".join(parts).strip()


async def retrieve_context(message: str, history: list[dict]) -> str:
    query = build_embed_query(history, message, config.EMBED_QUERY_TURNS)
    vector = await llm.embed(query)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}/points/search",
            json={"vector": vector, "limit": config.RETRIEVAL_LIMIT, "with_payload": True},
        )
        r.raise_for_status()
        points = r.json().get("result", [])
    chunks = [p.get("payload", {}).get("content", "") for p in points]
    chunks = [c for c in chunks if c]
    return "\n\n---\n\n".join(chunks)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd chat && python -m pytest tests/test_rag.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add chat/api/rag.py chat/tests/test_rag.py
git commit -m "feat(chat): RAG retrieval with history-aware query"
```

---

## Task 4: Database layer (asyncpg pool + schema)

**Files:**
- Create: `chat/api/db.py`
- Test: `chat/tests/test_memory.py` (db init covered indirectly; pool tested with monkeypatch)

- [ ] **Step 1: Write the failing test**

`chat/tests/test_memory.py` (db portion first):

```python
from api import db


def test_schema_sql_has_tables():
    sql = db.SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS conversations" in sql
    assert "CREATE TABLE IF NOT EXISTS messages" in sql
    assert "session_token" in sql
    assert "conversation_id" in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd chat && python -m pytest tests/test_memory.py::test_schema_sql_has_tables -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.db'`

- [ ] **Step 3: Write minimal implementation**

`chat/api/db.py`:

```python
import asyncpg
from api import config

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
  id            BIGSERIAL PRIMARY KEY,
  session_token TEXT NOT NULL,
  created_at    TIMESTAMPTZ DEFAULT now(),
  last_active   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conv_token ON conversations(session_token);

CREATE TABLE IF NOT EXISTS messages (
  id              BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT REFERENCES conversations(id),
  role            TEXT NOT NULL,
  content         TEXT NOT NULL,
  created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
"""

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(config.DATABASE_URL)
        async with _pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized")
    return _pool
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd chat && python -m pytest tests/test_memory.py::test_schema_sql_has_tables -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add chat/api/db.py chat/tests/test_memory.py
git commit -m "feat(chat): asyncpg pool + schema init"
```

---

## Task 5: Memory (conversation/message CRUD)

**Files:**
- Create: `chat/api/memory.py`
- Modify: `chat/tests/test_memory.py` (add CRUD tests with a fake pool)

- [ ] **Step 1: Write the failing test**

Append to `chat/tests/test_memory.py`:

```python
import pytest
from api import memory


class FakeConn:
    def __init__(self, store): self.store = store
    async def fetchval(self, sql, *args):
        if "INSERT INTO conversations" in sql:
            self.store["conv_id"] = 1
            return 1
        if "SELECT id FROM conversations" in sql:
            return self.store.get("conv_id")
        return None
    async def execute(self, sql, *args):
        if "INSERT INTO messages" in sql:
            self.store.setdefault("msgs", []).append((args[0], args[1], args[2]))
        return "OK"
    async def fetch(self, sql, *args):
        return [
            {"role": r, "content": c}
            for (_cid, r, c) in self.store.get("msgs", [])
        ]


class FakeAcquire:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *a): return False


class FakePool:
    def __init__(self): self.conn = FakeConn({})
    def acquire(self): return FakeAcquire(self.conn)


@pytest.mark.asyncio
async def test_get_or_create_and_history(monkeypatch):
    fake = FakePool()
    monkeypatch.setattr(memory.db, "pool", lambda: fake)

    conv_id = await memory.get_or_create_conversation("tok-123")
    assert conv_id == 1

    await memory.save_message(conv_id, "user", "que becas hay")
    await memory.save_message(conv_id, "assistant", "Beca MEC...")

    hist = await memory.load_history(conv_id, limit=6)
    assert hist == [
        {"role": "user", "content": "que becas hay"},
        {"role": "assistant", "content": "Beca MEC..."},
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd chat && python -m pytest tests/test_memory.py::test_get_or_create_and_history -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.memory'`

- [ ] **Step 3: Write minimal implementation**

`chat/api/memory.py`:

```python
from api import db


async def get_or_create_conversation(session_token: str) -> int:
    async with db.pool().acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM conversations WHERE session_token = $1 "
            "ORDER BY id DESC LIMIT 1",
            session_token,
        )
        if existing:
            return existing
        return await conn.fetchval(
            "INSERT INTO conversations (session_token) VALUES ($1) RETURNING id",
            session_token,
        )


async def save_message(conversation_id: int, role: str, content: str) -> None:
    async with db.pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1, $2, $3)",
            conversation_id, role, content,
        )
        await conn.execute(
            "UPDATE conversations SET last_active = now() WHERE id = $1",
            conversation_id,
        )


async def load_history(conversation_id: int, limit: int) -> list[dict]:
    async with db.pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content FROM messages WHERE conversation_id = $1 "
            "ORDER BY id DESC LIMIT $2",
            conversation_id, limit,
        )
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
```

> Note: the FakeConn in the test ignores the `UPDATE conversations` execute and the
> ORDER BY/reversed ordering (it stores in insert order and returns it). The real query
> fetches newest-first then reverses to chronological. Test asserts chronological order,
> which matches insert order in the fake — consistent.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd chat && python -m pytest tests/test_memory.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add chat/api/memory.py chat/tests/test_memory.py
git commit -m "feat(chat): conversation + message persistence"
```

---

## Task 6: FastAPI app (/health, /history, /chat SSE)

**Files:**
- Create: `chat/api/main.py`
- Test: `chat/tests/test_main.py`

- [ ] **Step 1: Write the failing test**

`chat/tests/test_main.py`:

```python
import pytest
from fastapi.testclient import TestClient
from api import main


@pytest.fixture(autouse=True)
def stub_deps(monkeypatch):
    # no real DB / Ollama / Qdrant in tests
    async def fake_init(): return None
    async def fake_close(): return None
    monkeypatch.setattr(main.db, "init_pool", fake_init)
    monkeypatch.setattr(main.db, "close_pool", fake_close)

    async def fake_conv(token): return 42
    async def fake_save(cid, role, content): return None
    async def fake_hist(cid, limit): return [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "Hola, soy SecretarIABot"},
    ]
    monkeypatch.setattr(main.memory, "get_or_create_conversation", fake_conv)
    monkeypatch.setattr(main.memory, "save_message", fake_save)
    monkeypatch.setattr(main.memory, "load_history", fake_hist)

    async def fake_ctx(message, history): return "CONTEXTO DAM"
    monkeypatch.setattr(main.rag, "retrieve_context", fake_ctx)

    async def fake_stream(system, prompt):
        for t in ["Hola", " mundo"]:
            yield t
    monkeypatch.setattr(main.llm, "generate_stream", fake_stream)


def test_health():
    with TestClient(main.app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_history_returns_messages():
    with TestClient(main.app) as client:
        r = client.get("/history/tok-123")
        assert r.status_code == 200
        body = r.json()
        assert body["messages"][0]["content"] == "hola"


def test_chat_streams_tokens():
    with TestClient(main.app) as client:
        r = client.post("/chat", json={"message": "que es DAM", "session_token": "tok-1"})
        assert r.status_code == 200
        text = r.text
        # SSE frames contain the streamed tokens
        assert "Hola" in text
        assert "mundo" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd chat && python -m pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.main'`

- [ ] **Step 3: Write minimal implementation**

`chat/api/main.py`:

```python
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from api import config, db, memory, rag, llm


class ChatRequest(BaseModel):
    message: str
    session_token: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    yield
    await db.close_pool()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/history/{session_token}")
async def history(session_token: str):
    conv_id = await memory.get_or_create_conversation(session_token)
    msgs = await memory.load_history(conv_id, config.HISTORY_TURNS)
    return JSONResponse({"messages": msgs})


def _sse(data: str) -> str:
    return f"data: {json.dumps({'token': data})}\n\n"


@app.post("/chat")
async def chat(req: ChatRequest):
    conv_id = await memory.get_or_create_conversation(req.session_token)
    hist = await memory.load_history(conv_id, config.HISTORY_TURNS)

    async def event_stream():
        try:
            context = await rag.retrieve_context(req.message, hist)
            hist_text = "\n".join(f"{m['role']}: {m['content']}" for m in hist)
            prompt = (
                f"HISTORIAL:\n{hist_text}\n\n"
                f"CONTEXTO:\n{context}\n\n"
                f"PREGUNTA: {req.message}"
            )
            full = []
            async for tok in llm.generate_stream(config.SYSTEM_PROMPT, prompt):
                full.append(tok)
                yield _sse(tok)
            answer = "".join(full)
            await memory.save_message(conv_id, "user", req.message)
            await memory.save_message(conv_id, "assistant", answer)
            yield "data: [DONE]\n\n"
        except Exception as e:  # noqa: BLE001
            yield _sse("Lo siento, ha ocurrido un error. Inténtalo de nuevo o consulta secretaría.")
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd chat && python -m pytest tests/test_main.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full test suite**

Run: `cd chat && python -m pytest -v`
Expected: PASS (all tasks' tests green)

- [ ] **Step 6: Commit**

```bash
git add chat/api/main.py chat/tests/test_main.py
git commit -m "feat(chat): FastAPI app with SSE /chat, /history, /health"
```

---

## Task 7: Widget (HTML/CSS/JS)

**Files:**
- Create: `chat/widget/index.html`
- Create: `chat/widget/style.css`
- Create: `chat/widget/chat.js`

> Frontend is verified manually in the browser (Task 10). No unit test framework for vanilla JS here; keep it small and readable.

- [ ] **Step 1: Create index.html**

`chat/widget/index.html`:

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Asistente Centro de FP Ejemplo</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div id="chat">
    <header id="chat-header">Asistente Centro de FP Ejemplo</header>
    <div id="messages" aria-live="polite"></div>
    <form id="composer">
      <input id="input" type="text" autocomplete="off"
             placeholder="Escribe tu pregunta..." required>
      <button type="submit">Enviar</button>
    </form>
  </div>
  <script src="chat.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create style.css**

`chat/widget/style.css`:

```css
:root { --brand: #0b5394; --bg: #f4f6f8; --user: #d7e9fb; --bot: #ffffff; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; background: var(--bg); }
#chat { max-width: 640px; margin: 0 auto; height: 100vh; display: flex; flex-direction: column; }
#chat-header { background: var(--brand); color: #fff; padding: 14px 18px; font-weight: 600; }
#messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.msg { max-width: 80%; padding: 10px 14px; border-radius: 12px; white-space: pre-wrap; line-height: 1.4; }
.msg.user { align-self: flex-end; background: var(--user); }
.msg.bot { align-self: flex-start; background: var(--bot); border: 1px solid #e2e6ea; }
#composer { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #e2e6ea; background: #fff; }
#input { flex: 1; padding: 10px 12px; border: 1px solid #cbd2d9; border-radius: 8px; font-size: 15px; }
button { background: var(--brand); color: #fff; border: 0; padding: 0 18px; border-radius: 8px; cursor: pointer; font-size: 15px; }
button:disabled { opacity: .5; cursor: default; }
```

- [ ] **Step 3: Create chat.js**

`chat/widget/chat.js`:

```javascript
const messagesEl = document.getElementById("messages");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const button = form.querySelector("button");

// login-less identity: persistent per-browser token
let token = localStorage.getItem("secretaria_token");
if (!token) {
  token = crypto.randomUUID();
  localStorage.setItem("secretaria_token", token);
}

function addMessage(text, who) {
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

async function loadHistory() {
  try {
    const r = await fetch(`/history/${token}`);
    const data = await r.json();
    (data.messages || []).forEach(m =>
      addMessage(m.content, m.role === "user" ? "user" : "bot"));
  } catch (e) { /* nuevo usuario sin historial */ }
}

async function send(message) {
  addMessage(message, "user");
  const botDiv = addMessage("", "bot");
  button.disabled = true;

  const resp = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_token: token }),
  });

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop();
    for (const frame of frames) {
      const line = frame.replace(/^data: /, "").trim();
      if (!line || line === "[DONE]") continue;
      try {
        const obj = JSON.parse(line);
        if (obj.token) {
          botDiv.textContent += obj.token;
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
      } catch (e) { /* frame parcial, ignorar */ }
    }
  }
  button.disabled = false;
  input.focus();
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  send(message);
});

loadHistory();
```

- [ ] **Step 4: Commit**

```bash
git add chat/widget/index.html chat/widget/style.css chat/widget/chat.js
git commit -m "feat(chat): login-less streaming chat widget"
```

---

## Task 8: Dockerfile + compose service + nginx

**Files:**
- Create: `chat/Dockerfile`
- Create: `nginx/chat.conf`
- Modify: `docker-compose.yml` (add `secretaria-api` service + 3444 port on nginx-viewer)

- [ ] **Step 1: Create Dockerfile**

`chat/Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api ./api
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create nginx/chat.conf**

`nginx/chat.conf`:

```nginx
server {
    listen 444 ssl;
    server_name _;

    ssl_certificate     /etc/nginx/certs/localhost.pem;
    ssl_certificate_key /etc/nginx/certs/localhost-key.pem;

    # Widget estático
    location / {
        root /usr/share/nginx/chat;
        index index.html;
    }

    # API: chat (SSE) + history
    location ~ ^/(chat|history) {
        proxy_pass http://secretaria-api:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;          # crítico para streaming SSE
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

> `listen 444` inside the container is mapped to host `3444` in compose. `proxy_buffering off`
> is required or nginx buffers the SSE stream and breaks token-by-token delivery.

- [ ] **Step 3: Modify docker-compose.yml — add service**

Add this service block under `services:` (e.g. after the `qdrant` service, before `volumes:`):

```yaml
  # 6. API de chat con streaming (FastAPI) — coexiste con n8n/Typebot
  secretaria-api:
    build: ./chat
    container_name: secretaria_api
    environment:
      - OLLAMA_URL=http://host.docker.internal:11434
      - QDRANT_URL=http://qdrant:6333
      - QDRANT_COLLECTION=secretaria
      - EMBED_MODEL=mxbai-embed-large:latest
      - LLM_MODEL=llama3.1:8b
      - RETRIEVAL_LIMIT=8
      - NUM_PREDICT=400
      - HISTORY_TURNS=6
      - EMBED_QUERY_TURNS=3
      - DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/secretaria_chat
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      - postgres
      - qdrant
    restart: always
```

- [ ] **Step 4: Modify docker-compose.yml — nginx-viewer port + widget mount**

In the existing `nginx-viewer` service, add port `3444` and mount the widget + chat.conf.
Change its `ports:` and `volumes:` to:

```yaml
    ports:
      - "3443:443"
      - "3444:444"
    volumes:
      - ./nginx/viewer.conf:/etc/nginx/conf.d/default.conf:ro
      - ./nginx/chat.conf:/etc/nginx/conf.d/chat.conf:ro
      - ./chat/widget:/usr/share/nginx/chat:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on:
      - typebot-viewer
      - secretaria-api
```

> Only `ports`, `volumes`, `depends_on` of nginx-viewer change. The `viewer.conf` (3443
> Typebot) line is preserved — both server blocks load. No existing service removed.

- [ ] **Step 5: Create the database (one-time)**

The `postgres` container already runs n8n's DB. Create the new DB once:

Run:
```bash
docker exec postgres_db psql -U "$POSTGRES_USER" -c "CREATE DATABASE secretaria_chat;"
```
Expected: `CREATE DATABASE` (or "already exists" — harmless). The app's `init_pool()`
creates the tables on first start.

- [ ] **Step 6: Commit**

```bash
git add chat/Dockerfile nginx/chat.conf docker-compose.yml
git commit -m "feat(chat): dockerize api + nginx 3444 widget (coexists with 3443)"
```

---

## Task 9: Deploy to DGX + smoke test

**Files:** none (deployment)

- [ ] **Step 1: Pull on DGX**

Run:
```bash
ssh dgx "cd ~/SecretarIA && git pull"
```
Expected: fast-forward to latest.

- [ ] **Step 2: Create DB + build + start the new service only**

Run:
```bash
ssh dgx "cd ~/SecretarIA && docker exec postgres_db psql -U \$POSTGRES_USER -c 'CREATE DATABASE secretaria_chat;' 2>&1 | tail -1; docker compose up -d --build secretaria-api nginx-viewer"
```
Expected: `secretaria_api` built and started; `nginx_viewer` recreated with port 3444.

- [ ] **Step 3: Health check**

Run:
```bash
ssh dgx "curl -s http://localhost:8000/health || docker exec secretaria_api curl -s http://localhost:8000/health"
```
Expected: `{"status":"ok"}`

- [ ] **Step 4: Smoke test the streaming endpoint**

Run:
```bash
ssh dgx "curl -s -N -X POST http://localhost:8000/chat -H 'Content-Type: application/json' -d '{\"message\":\"que modulos tiene DAM\",\"session_token\":\"smoke-1\"}' | head -20"
```
Expected: multiple `data: {"token": "..."}` SSE frames, ending with `data: [DONE]`.

- [ ] **Step 5: Verify persistence**

Run:
```bash
ssh dgx "curl -s http://localhost:8000/history/smoke-1"
```
Expected: JSON with the user message "que modulos tiene DAM" and the assistant answer.

- [ ] **Step 6: Commit (if any deploy notes/fixes)**

No code change expected. If deployment required a fix, commit it with a clear message.

---

## Task 10: Browser verification + README

**Files:**
- Modify: `README.md` (add a short section on the new chat service)

- [ ] **Step 1: Manual browser test**

Over the VPN, open `https://10.0.0.10:3444/` in a browser.
Verify:
- Widget loads, header "Asistente Centro de FP Ejemplo".
- Ask "que modulos tiene DAM" → tokens appear progressively (streaming visible).
- Ask a follow-up "y el horario?" → answer uses prior context.
- Reload the page → previous messages reappear (history via localStorage token).

- [ ] **Step 2: Add README section**

Add to `README.md` (after the Workflows section), document:

```markdown
## Chat con streaming (FastAPI — arquitectura alternativa, en evaluación)

Servicio alternativo a Typebot+n8n que añade respuestas en streaming (token a token)
con widget propio sin login. **Coexiste** con el stack n8n/Typebot; no lo reemplaza
hasta decidir adopción.

- Backend: `chat/api` (FastAPI, SSE). Widget: `chat/widget` (HTML/JS).
- Acceso: `https://<servidor>:3444/` (Typebot sigue en 3443).
- BD propia `secretaria_chat` en el Postgres existente (historial + analytics).
- Reusa Qdrant (`secretaria`) y Ollama (`llama3.1:8b`).

Arrancar:
```bash
docker compose up -d --build secretaria-api nginx-viewer
```

Diseño completo: `docs/superpowers/specs/2026-06-04-fastapi-streaming-chat-design.md`
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document FastAPI streaming chat service (3444)"
```

---

## Self-Review notes

- **Spec coverage:** widget (T7), FastAPI SSE (T6), rag history-aware (T3), llm streaming (T2),
  memory/Postgres new DB (T4/T5), config incl. validated prompt (T1), nginx 3444 + compose
  additive (T8), deploy/smoke (T9), browser + README (T10). Coexistence honored: no service
  removed; new DB; new port. Error handling covered in T6 event_stream try/except + degrade.
- **Out of scope (YAGNI):** analytics dashboard, vLLM, accounts, OpenWebUI — not in tasks, by design.
- **Type consistency:** `embed`/`generate_stream` (llm) used by rag/main; `retrieve_context`,
  `build_embed_query` (rag); `get_or_create_conversation`/`save_message`/`load_history`
  (memory); `init_pool`/`close_pool`/`pool` (db) — names consistent across tasks.
- **Note on history-aware turns:** `EMBED_QUERY_TURNS` (embedding) vs `HISTORY_TURNS` (prompt
  history) are distinct by design.
