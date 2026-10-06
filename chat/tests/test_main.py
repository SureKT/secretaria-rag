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
        {"role": "assistant", "content": "Hola, soy NorteBot"},
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
        assert "Hola" in text
        assert "mundo" in text


def test_chat_rejects_oversized_token():
    with TestClient(main.app) as client:
        r = client.post("/chat", json={"message": "hola", "session_token": "x" * 65})
        assert r.status_code == 422


def test_chat_rejects_empty_message():
    with TestClient(main.app) as client:
        r = client.post("/chat", json={"message": "", "session_token": "tok-1"})
        assert r.status_code == 422


def test_history_rejects_oversized_token():
    with TestClient(main.app) as client:
        r = client.get("/history/" + "x" * 65)
        assert r.status_code == 422


def test_chat_emits_suggestions_event(monkeypatch):
    async def fake_stream_with_sentinel(system, prompt):
        for t in [
            "DAM tiene módulos.",
            "\n[[SEGUIMIENTO]]\n",
            "- ¿Plazo de matrícula?\n",
            "- ¿Salidas?\n",
        ]:
            yield t
    monkeypatch.setattr(main.llm, "generate_stream", fake_stream_with_sentinel)

    saved = []
    async def capture_save(cid, role, content):
        saved.append((role, content))
    monkeypatch.setattr(main.memory, "save_message", capture_save)

    with TestClient(main.app) as client:
        r = client.post("/chat", json={"message": "modulos DAM", "session_token": "tok-s"})
        assert r.status_code == 200
        text = r.text
        # El centinela nunca se filtra al cliente
        assert "[[SEGUIMIENTO]]" not in text
        assert "SEGUIMIENTO" not in text
        # Llega un evento suggestions con las preguntas
        assert '"suggestions"' in text
        assert "¿Plazo de matrícula?" in text
        # Lo persistido como respuesta excluye el bloque de seguimiento
        assistant = [c for (role, c) in saved if role == "assistant"][0]
        assert "[[SEGUIMIENTO]]" not in assistant
        assert assistant.strip() == "DAM tiene módulos."


def test_chat_without_sentinel_has_no_suggestions():
    # Usa el fake por defecto del fixture (yields "Hola"/" mundo", sin centinela)
    with TestClient(main.app) as client:
        r = client.post("/chat", json={"message": "hola", "session_token": "tok-2"})
        assert r.status_code == 200
        assert '"suggestions"' not in r.text
        assert "Hola" in r.text and "mundo" in r.text
