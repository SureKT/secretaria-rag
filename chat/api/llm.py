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
