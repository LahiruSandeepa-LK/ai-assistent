"""Provider-timeout fallback chain + per-session token cap. docs/14 §2-3."""
import time

import pytest

from llm.gateway import ModelGateway
from llm.provider import BaseProvider, Completion
from memory.usage import SessionUsageStore, get_session_usage, reset_session_usage


class _Slow(BaseProvider):
    name = "slow"

    def __init__(self, delay):
        self.delay = delay

    def complete(self, system, user, *, model="strong"):
        time.sleep(self.delay)
        return Completion("slow-answer", 1, 1)


class _Fast(BaseProvider):
    name = "fast"

    def complete(self, system, user, *, model="strong"):
        return Completion("fast-answer", 2, 3)


class _Boom(BaseProvider):
    name = "boom"

    def complete(self, system, user, *, model="strong"):
        raise RuntimeError("provider down")


def test_timeout_switches_to_next_provider(monkeypatch):
    monkeypatch.setenv("LLM_CALL_TIMEOUT", "0.3")
    gw = ModelGateway(provider=_Slow(5.0), fallback=_Fast())
    t0 = time.time()
    c = gw.complete("sys", "hi")
    assert c.text == "fast-answer"          # primary timed out -> fell back to fast
    assert c.provider == "fast"
    assert not c.timed_out
    assert time.time() - t0 < 2.0            # didn't wait for the 5s slow provider


def test_error_switches_to_next_provider(monkeypatch):
    monkeypatch.setenv("LLM_CALL_TIMEOUT", "5")
    gw = ModelGateway(provider=_Boom(), fallback=_Fast())
    c = gw.complete("sys", "hi")
    assert c.text == "fast-answer" and c.provider == "fast"


def test_all_providers_exhausted_returns_timeout(monkeypatch):
    monkeypatch.setenv("LLM_CALL_TIMEOUT", "0.2")
    gw = ModelGateway(provider=_Slow(3.0), fallback=_Slow(3.0))
    c = gw.complete("sys", "hi")
    assert c.timed_out and c.provider == "timeout"
    assert "longer than usual" in c.text


def test_session_cap(monkeypatch):
    monkeypatch.setenv("SESSION_TOKEN_CAP", "100")
    s = SessionUsageStore()
    assert not s.over_cap("sA") and s.remaining("sA") == 100
    s.record("sA", 60)
    assert s.get("sA") == 60 and s.remaining("sA") == 40 and not s.over_cap("sA")
    s.record("sA", 50)
    assert s.get("sA") == 110 and s.over_cap("sA") and s.remaining("sA") == 0
    assert not s.over_cap("sB")               # other sessions unaffected


def test_session_cap_disabled(monkeypatch):
    monkeypatch.setenv("SESSION_TOKEN_CAP", "0")
    s = SessionUsageStore()
    s.record("x", 10_000_000)
    assert not s.over_cap("x")


def test_session_store_singleton_reset():
    reset_session_usage()
    assert isinstance(get_session_usage(), SessionUsageStore)
