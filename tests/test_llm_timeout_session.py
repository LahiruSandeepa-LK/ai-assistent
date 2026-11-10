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


# ---- transient-error retry (Gemini 503 etc.) -------------------------------------------------
class _Flaky(BaseProvider):
    name = "flaky"

    def __init__(self, fails, exc):
        self.calls = 0
        self.fails = fails
        self.exc = exc

    def complete(self, system, user, *, model="strong"):
        self.calls += 1
        if self.calls <= self.fails:
            raise self.exc
        return Completion("recovered", 1, 1)


def test_is_retryable_classifier():
    from llm.gateway import _is_retryable
    assert _is_retryable(RuntimeError("503 UNAVAILABLE. high demand"))          # Gemini overload
    assert _is_retryable(RuntimeError("429 rate limit exceeded, try again"))    # transient 429
    assert not _is_retryable(RuntimeError("429 - You have no credits remaining"))  # billing
    assert not _is_retryable(RuntimeError("401 invalid api key"))
    assert not _is_retryable(RuntimeError("400 bad request"))


def test_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setenv("LLM_CALL_TIMEOUT", "5")
    monkeypatch.setenv("LLM_RETRY_MAX", "3")
    monkeypatch.setenv("LLM_RETRY_BASE", "0.01")
    p = _Flaky(2, RuntimeError("503 UNAVAILABLE high demand"))   # fails twice, then succeeds
    gw = ModelGateway(provider=p, fallback=None)
    c = gw.complete("s", "u")
    assert c.text == "recovered" and p.calls == 3 and not c.timed_out


def test_non_retryable_skips_to_fallback(monkeypatch):
    monkeypatch.setenv("LLM_CALL_TIMEOUT", "5")
    monkeypatch.setenv("LLM_RETRY_MAX", "3")
    monkeypatch.setenv("LLM_RETRY_BASE", "0.01")
    p = _Flaky(99, RuntimeError("429 - You have no credits remaining"))   # hard failure
    gw = ModelGateway(provider=p, fallback=_Fast())
    c = gw.complete("s", "u")
    assert c.text == "fast-answer" and p.calls == 1   # failed fast, no wasted retries
