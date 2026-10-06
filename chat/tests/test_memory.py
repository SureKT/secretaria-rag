from api import db


def test_schema_sql_has_tables():
    sql = db.SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS conversations" in sql
    assert "CREATE TABLE IF NOT EXISTS messages" in sql
    assert "session_token" in sql
    assert "conversation_id" in sql


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
        msgs = self.store.get("msgs", [])
        # simulate ORDER BY id DESC: newest first
        ordered = list(reversed(msgs))
        return [
            {"role": r, "content": c}
            for (_cid, r, c) in ordered
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
