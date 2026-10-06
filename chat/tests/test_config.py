from api import config


def test_defaults_present():
    assert config.LLM_MODEL  # non-empty
    assert config.EMBED_MODEL
    assert config.RETRIEVAL_LIMIT == 12
    assert config.HISTORY_TURNS == 6
    assert config.EMBED_QUERY_TURNS == 3
    assert "NorteBot" in config.SYSTEM_PROMPT
    assert "secretar" in config.SYSTEM_PROMPT.lower()


def test_env_override(monkeypatch):
    # reload mutates the shared config module; restore it afterwards so test
    # order can't leak RETRIEVAL_LIMIT=5 into other tests in the same process.
    import importlib
    monkeypatch.setenv("RETRIEVAL_LIMIT", "5")
    importlib.reload(config)
    try:
        assert config.RETRIEVAL_LIMIT == 5
    finally:
        monkeypatch.delenv("RETRIEVAL_LIMIT", raising=False)
        importlib.reload(config)
