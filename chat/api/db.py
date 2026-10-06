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

-- Idempotent migration: collapse duplicate conversations per session_token and
-- add a UNIQUE constraint so get_or_create_conversation can rely on
-- INSERT ... ON CONFLICT (atomic, race-free). Skips if constraint already exists.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'conversations_session_token_key'
  ) THEN
    -- Re-point messages of older duplicates to the newest conversation per token.
    UPDATE messages m
       SET conversation_id = keep.max_id
      FROM conversations c
      JOIN (
        SELECT session_token, MAX(id) AS max_id
          FROM conversations GROUP BY session_token
      ) keep ON keep.session_token = c.session_token
     WHERE m.conversation_id = c.id
       AND c.id <> keep.max_id;
    -- Drop the now-orphaned older duplicate conversations.
    DELETE FROM conversations c
     USING (
        SELECT session_token, MAX(id) AS max_id
          FROM conversations GROUP BY session_token
      ) keep
     WHERE keep.session_token = c.session_token
       AND c.id <> keep.max_id;
    ALTER TABLE conversations
      ADD CONSTRAINT conversations_session_token_key UNIQUE (session_token);
  END IF;
END $$;
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
