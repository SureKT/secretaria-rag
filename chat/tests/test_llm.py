import json
import pytest
import httpx
from api import llm


@pytest.mark.asyncio
async def test_embed_returns_vector(monkeypatch):
    async def fake_post(self, url, json=None, **kw):
        req = httpx.Request("POST", url)
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]}, request=req)
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
