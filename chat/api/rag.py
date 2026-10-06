import httpx
from api import config, llm


def build_embed_query(history: list[dict], message: str, turns: int) -> str:
    """Concat the last `turns` user messages + current message for a richer
    embedding that survives context-less follow-ups ("y el horario?")."""
    user_msgs = [m["content"] for m in history if m["role"] == "user"]
    recent = user_msgs[-(turns - 1):] if turns > 1 else []
    parts = recent + [message]
    return " ".join(parts).strip()


def _tenant_filter() -> dict:
    """Filtro multi-tenant (ADR-002): el centro actual SOLO ve sus chunks + los
    'shared'. Se aplica SIEMPRE para evitar fugas entre centros."""
    return {
        "should": [
            {"key": "tenant", "match": {"value": config.TENANT}},
            {"key": "tenant", "match": {"value": config.SHARED_TENANT}},
        ]
    }


async def retrieve_context(message: str, history: list[dict]) -> str:
    query = build_embed_query(history, message, config.EMBED_QUERY_TURNS)
    vector = await llm.embed(query)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}/points/search",
            json={
                "vector": vector,
                "limit": config.RETRIEVAL_LIMIT,
                "with_payload": True,
                "filter": _tenant_filter(),
            },
        )
        r.raise_for_status()
        points = r.json().get("result", [])
    chunks = [p.get("payload", {}).get("content", "") for p in points]
    chunks = [c for c in chunks if c]
    return "\n\n---\n\n".join(chunks)
