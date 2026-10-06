import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Path
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from api import config, db, memory, rag, llm
from api.streaming import AnswerSplitter

logger = logging.getLogger("secretaria-api")

# Browser token is a UUID (36 chars); 64 leaves margin without letting a public
# endpoint accept unbounded strings.
TOKEN_MAX = 64


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_token: str = Field(min_length=1, max_length=TOKEN_MAX)


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
async def history(session_token: str = Path(min_length=1, max_length=TOKEN_MAX)):
    conv_id = await memory.get_or_create_conversation(session_token)
    msgs = await memory.load_history(conv_id, config.HISTORY_TURNS)
    return JSONResponse({"messages": msgs})


def _sse(data: str) -> str:
    # ensure_ascii=False: acentos literales (español) → payloads menores y SSE legible.
    return f"data: {json.dumps({'token': data}, ensure_ascii=False)}\n\n"


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
            splitter = AnswerSplitter()
            async for tok in llm.generate_stream(config.SYSTEM_PROMPT, prompt):
                emit = splitter.feed(tok)
                if emit:
                    yield _sse(emit)
            tail = splitter.finish()
            if tail:
                yield _sse(tail)
            answer = splitter.answer_text().strip()
            suggestions = splitter.suggestions()
            await memory.save_message(conv_id, "user", req.message)
            await memory.save_message(conv_id, "assistant", answer)
            if suggestions:
                yield f"data: {json.dumps({'suggestions': suggestions}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception:  # noqa: BLE001
            logger.exception("error generating chat response")
            yield _sse("Lo siento, ha ocurrido un error. Inténtalo de nuevo o consulta secretaría.")
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
