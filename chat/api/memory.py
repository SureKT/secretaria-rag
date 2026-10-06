from api import db


async def get_or_create_conversation(session_token: str) -> int:
    # Single atomic statement: relies on UNIQUE(session_token). Concurrent
    # requests with the same new token can no longer create duplicate rows
    # (the loser hits ON CONFLICT and gets the existing id back).
    async with db.pool().acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO conversations (session_token) VALUES ($1) "
            "ON CONFLICT (session_token) DO UPDATE SET last_active = now() "
            "RETURNING id",
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
