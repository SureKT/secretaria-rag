import pytest
import httpx
from api import rag, config


def test_tenant_filter_includes_current_and_shared(monkeypatch):
    monkeypatch.setattr(config, "TENANT", "sur")
    f = rag._tenant_filter()
    values = {c["match"]["value"] for c in f["should"]}
    assert values == {"sur", "shared"}


def test_build_embed_query_concats_last_user_turns():
    history = [
        {"role": "user", "content": "que modulos tiene DAM"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "y el horario?"},
    ]
    q = rag.build_embed_query(history, "y la sede?", turns=3)
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
        req = httpx.Request("POST", url)
        return httpx.Response(200, json={"result": [
            {"payload": {"content": "DAM tiene Programacion"}},
            {"payload": {"content": "Bases de datos"}},
        ]}, request=req)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    ctx = await rag.retrieve_context("que modulos DAM", [])
    assert "DAM tiene Programacion" in ctx
    assert "Bases de datos" in ctx


@pytest.mark.asyncio
async def test_search_applies_tenant_filter(monkeypatch):
    """La query a Qdrant DEBE incluir el filtro por tenant (aislamiento ADR-002)."""
    monkeypatch.setattr(config, "TENANT", "sur")

    async def fake_embed(text):
        return [0.1]
    monkeypatch.setattr(rag.llm, "embed", fake_embed)

    captured = {}

    async def fake_post(self, url, json=None, **kw):
        captured["json"] = json
        req = httpx.Request("POST", url)
        return httpx.Response(200, json={"result": []}, request=req)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    await rag.retrieve_context("xyz", [])
    flt = captured["json"]["filter"]
    values = {c["match"]["value"] for c in flt["should"]}
    assert values == {"sur", "shared"}


@pytest.mark.asyncio
async def test_search_empty_returns_empty_string(monkeypatch):
    async def fake_embed(text):
        return [0.1]
    monkeypatch.setattr(rag.llm, "embed", fake_embed)

    async def fake_post(self, url, json=None, **kw):
        req = httpx.Request("POST", url)
        return httpx.Response(200, json={"result": []}, request=req)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    ctx = await rag.retrieve_context("xyz", [])
    assert ctx == ""
