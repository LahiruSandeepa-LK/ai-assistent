"""LLM runtime-config store: create-only, write-only secret, activation, persistence."""
import json
import os

import pytest

from llm.config_store import LLMConfigStore, LLMConfig


def test_create_and_activate_in_memory():
    s = LLMConfigStore(persist=False)
    c1 = s.create("gemini", "gemini-pro-latest", "gemini-flash-latest", secret="KEY1")
    assert c1.active and c1.has_secret
    c2 = s.create("openai", "gpt-4.1", "gpt-4.1-mini", secret="KEY2", activate=True)
    # activating c2 deactivates c1
    assert s.get_active().id == c2.id
    assert not [c for c in s.list() if c.id == c1.id][0].active


def test_secret_is_write_only_never_in_public_view():
    s = LLMConfigStore(persist=False)
    c = s.create("gemini", "m-strong", "m-fast", secret="SUPERSECRET")
    # The public dataclass has no secret attribute at all.
    assert not hasattr(c, "secret")
    assert "SUPERSECRET" not in json.dumps(c.__dict__)
    for pub in s.list():
        assert "SUPERSECRET" not in json.dumps(pub.__dict__)
    # Secret is reachable ONLY via the internal accessor.
    assert s.secret_for(c.id) == "SUPERSECRET"


def test_no_update_method_exists():
    # create-only by design: there must be no way to edit a config after creation
    assert not hasattr(LLMConfigStore, "update")
    assert not hasattr(LLMConfigStore, "edit")
    assert not hasattr(LLMConfigStore, "set_secret")


def test_unsupported_provider_rejected():
    s = LLMConfigStore(persist=False)
    with pytest.raises(ValueError):
        s.create("doesnotexist", "a", "b")


def test_persistence_reads_back_without_leaking_secret(tmp_path):
    path = str(tmp_path / "llm.json")
    s1 = LLMConfigStore(path=path, persist=True)
    c = s1.create("anthropic", "claude-sonnet-4-5", "claude-haiku-4-5", secret="TOPSECRET")
    # a second store instance (another process) sees the config + can resolve the secret in-proc
    s2 = LLMConfigStore(path=path, persist=True)
    assert s2.get_active().id == c.id
    assert s2.secret_for(c.id) == "TOPSECRET"
    # the file is server-side only; the API layer never returns the secret (verified elsewhere),
    # but confirm the public views carry no secret field
    assert all(not hasattr(x, "secret") for x in s2.list())


def test_delete_removes_config_and_secret():
    s = LLMConfigStore(persist=False)
    c = s.create("mock", "", "", secret="")
    assert s.delete(c.id) is True
    assert s.get_active() is None
    assert s.secret_for(c.id) == ""


def test_provider_selection_uses_active_config(monkeypatch, tmp_path):
    # With an active mock config, get_provider returns MockProvider regardless of env.
    monkeypatch.setenv("LLM_CONFIG_PATH", str(tmp_path / "c.json"))
    monkeypatch.setenv("LLM_PROVIDER", "gemini")  # would otherwise try gemini
    import llm.config_store as cs
    cs.reset_config_store()
    cs.get_config_store().create("mock", "", "", secret="", activate=True)
    from llm.provider import get_provider
    assert get_provider().is_mock
    cs.reset_config_store()
