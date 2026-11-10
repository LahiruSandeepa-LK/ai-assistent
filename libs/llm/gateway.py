"""Model gateway: single entry for all LLM calls — provider routing + fallback +
token metering. ADR-010, docs/14."""
from __future__ import annotations

from typing import Callable, Optional

import os
import random
import time

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from .provider import BaseProvider, Completion, build_provider, get_provider

# How much of each prompt/response to log. Set LLM_LOG_FULL=true to log the complete text
# (otherwise previews are truncated to LLM_LOG_PREVIEW chars). docs/07.
_LOG_FULL = os.getenv("LLM_LOG_FULL", "false").lower() in ("1", "true", "yes")
_LOG_PREVIEW = int(os.getenv("LLM_LOG_PREVIEW", "500"))

# Per-provider wall-clock budget. If a provider doesn't respond within this many seconds we abandon
# it and switch to the next provider in the chain. Read live so it's env-configurable. docs/14 §2.
def _call_timeout() -> float:
    try:
        return float(os.getenv("LLM_CALL_TIMEOUT", "30"))
    except ValueError:
        return 30.0


# Shown to the customer when EVERY provider in the chain timed out or errored.
_TIMEOUT_MESSAGE = ("I'm sorry — I'm taking longer than usual to respond right now. Please try your "
                    "question again in a moment.")

# A small pool to run each (blocking) provider call under a timeout.
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm")


# ---- transient-error retry (ADR-003/E1) -------------------------------------------------------
# A provider error like Gemini's "503 UNAVAILABLE / high demand" is TEMPORARY — retrying the same
# provider after a short backoff usually succeeds, which is far better than cascading to a fallback
# that may be unavailable (e.g. an OpenAI key with no credits). We retry only *retryable* errors
# (503/500/502/504, rate-limit/overload, timeouts) and fail fast on hard errors (bad key, no
# credits, quota exhausted, 400/401/403/404) so we don't waste the per-provider time budget.
def _retry_max() -> int:
    try:
        return max(0, int(os.getenv("LLM_RETRY_MAX", "2")))   # extra attempts beyond the first
    except ValueError:
        return 2


def _retry_base() -> float:
    try:
        return float(os.getenv("LLM_RETRY_BASE", "0.6"))      # backoff base seconds
    except ValueError:
        return 0.6


_NON_RETRYABLE = ("no credits", "insufficient_quota", "insufficient quota", "quota exceeded",
                  "exceeded your current quota", "billing", "api key not valid", "invalid api key",
                  "invalid_api_key", "permission denied", "unauthorized", "forbidden",
                  "not found", "400", "401", "403", "404")
_RETRYABLE = ("503", "500", "502", "504", "unavailable", "overloaded", "high demand",
              "temporarily", "try again", "rate limit", "ratelimit", "429", "timeout",
              "timed out", "connection", "deadline")


def _status_code(exc: Exception):
    for attr in ("status_code", "code", "http_status"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    return None


def _is_retryable(exc: Exception) -> bool:
    """True = worth retrying the SAME provider (transient). False = fail fast, move to next."""
    blob = f"{type(exc).__name__}: {exc}".lower()
    if any(k in blob for k in _NON_RETRYABLE):   # hard failures win (e.g. a 429 that is 'no credits')
        return False
    code = _status_code(exc)
    if code in (500, 502, 503, 504, 429, 408):
        return True
    return any(k in blob for k in _RETRYABLE)


def _call_with_retry(provider: BaseProvider, system: str, user: str, model: str):
    """Call provider.complete, retrying transient failures with exponential backoff + jitter.
    The whole call is still bounded by the per-provider future timeout in _complete()."""
    import sys

    attempts = _retry_max() + 1
    base = _retry_base()
    pname = getattr(provider, "name", "?")
    for i in range(attempts):
        try:
            return provider.complete(system, user, model=model)
        except Exception as e:
            if i + 1 >= attempts or not _is_retryable(e):
                raise
            delay = min(base * (2 ** i), 5.0) + random.uniform(0, 0.25)
            print(f"[model-gateway] provider '{pname}' transient error "
                  f"(attempt {i + 1}/{attempts}): {e!r} — retrying in {delay:.1f}s",
                  file=sys.stderr, flush=True)
            time.sleep(delay)
    raise RuntimeError("retry loop exhausted")   # unreachable


def _clip(text: str) -> str:
    if _LOG_FULL or len(text) <= _LOG_PREVIEW:
        return text
    return text[:_LOG_PREVIEW] + f"…(+{len(text) - _LOG_PREVIEW} chars)"


class ModelGateway:
    def __init__(self, provider: Optional[BaseProvider] = None, fallback: Optional[BaseProvider] = None):
        self.provider = provider or get_provider()
        self.fallback = fallback
        # metering hook: fn(user_id, prompt_tokens, completion_tokens, model)
        self.on_usage: Optional[Callable[[str, int, int, str], None]] = None
        from observability.logging import get_logger

        self._log = get_logger("model-gateway")

    def complete(self, system: str, user: str, *, model: str = "strong", user_id: str = "") -> Completion:
        from observability.tracing import traced

        return traced(name="llm.complete", run_type="llm")(self._complete)(system, user, model=model, user_id=user_id)

    def _complete(self, system: str, user: str, *, model: str = "strong", user_id: str = "") -> Completion:
        # True service-to-service: when MODEL_GATEWAY_URL is set, call the ai-model-gateway service
        # over HTTP. If that service is unreachable/slow/erroring, degrade to a LOCAL completion
        # (provider -> mock) rather than propagating a 500 to the orchestrator.
        if os.getenv("MODEL_GATEWAY_URL"):
            from clients.services import remote_complete

            try:
                return remote_complete(system, user, model, user_id)
            except Exception as e:
                import sys

                print(f"[gateway] model-gateway service call failed: {e!r} — completing locally",
                      file=sys.stderr, flush=True)
                # fall through to the local path below

        from observability.logging import log
        import sys

        # Ordered provider chain: primary (LLM_PROVIDER) -> fallback (LLM_FALLBACK). Each gets its
        # own timeout window; if one times out or errors we move to the next. We do NOT add a
        # silent MockProvider here — when every real provider is exhausted we return a clear timeout
        # response to the caller instead of a fabricated answer. (In offline mode the primary IS the
        # mock, so it answers instantly and the chain never reaches a timeout.)
        chain: list[BaseProvider] = []
        for p in (self.provider, self.fallback):
            if p is not None and p not in chain:
                chain.append(p)

        provider_name = getattr(self.provider, "name", "?")
        # ---- log the LLM REQUEST (once) ----
        tmo = _call_timeout()
        log(self._log, "llm_request", provider=provider_name, model=model, user_id=user_id,
            chain=[getattr(p, "name", "?") for p in chain], timeout_s=tmo,
            system=_clip(system), prompt=_clip(user))

        last_err: Exception | None = None
        for p in chain:
            pname = getattr(p, "name", "?")
            t0 = time.time()
            try:
                fut = _POOL.submit(_call_with_retry, p, system, user, model)
                c = fut.result(timeout=tmo)
            except FutureTimeout as e:
                last_err = e
                fut.cancel()
                print(f"[model-gateway] provider '{pname}' timed out after {tmo:.0f}s for "
                      f"model '{model}' — switching to next provider", file=sys.stderr, flush=True)
                log(self._log, "llm_timeout", provider=pname, model=model, user_id=user_id,
                    timeout_s=tmo)
                continue
            except Exception as e:
                last_err = e
                print(f"[model-gateway] provider '{pname}' failed for model '{model}': {e!r} — "
                      f"switching to next provider", file=sys.stderr, flush=True)
                continue
            # success
            c.provider = pname
            log(self._log, "llm_response", provider=pname, model=model, user_id=user_id,
                latency_ms=int((time.time() - t0) * 1000), prompt_tokens=c.prompt_tokens,
                completion_tokens=c.completion_tokens, total_tokens=c.total_tokens,
                response=_clip(c.text))
            if self.on_usage:
                try:
                    self.on_usage(user_id, c.prompt_tokens, c.completion_tokens, model)
                except Exception:
                    pass
            return c

        # every provider timed out / failed -> return a timeout completion (no mock, no 500)
        print(f"[model-gateway] all providers exhausted for model '{model}' "
              f"(last error: {last_err!r}) — returning timeout response", file=sys.stderr, flush=True)
        log(self._log, "llm_exhausted", model=model, user_id=user_id,
            tried=[getattr(p, "name", "?") for p in chain], last_error=repr(last_err))
        return Completion(_TIMEOUT_MESSAGE, 0, 0, provider="timeout", timed_out=True)


_GATEWAY: ModelGateway | None = None
_GATEWAY_CFG_VERSION: int = -1


def _config_version() -> int:
    try:
        from .config_store import get_config_store

        return get_config_store().version
    except Exception:
        return 0


def get_gateway() -> ModelGateway:
    """Return the process gateway, rebuilding it if the admin LLM config changed since it was
    built (so activating a new provider in the admin console takes effect live)."""
    global _GATEWAY, _GATEWAY_CFG_VERSION
    ver = _config_version()
    if _GATEWAY is None or ver != _GATEWAY_CFG_VERSION:
        # LLM_FALLBACK (e.g. "openai") gives provider resilience per ADR-003/E1.
        fallback = build_provider(os.getenv("LLM_FALLBACK", ""))
        _GATEWAY = ModelGateway(fallback=fallback)
        _GATEWAY_CFG_VERSION = ver
    return _GATEWAY


def reset_gateway() -> None:
    """Force the next get_gateway() to rebuild (e.g. right after an LLM config activate)."""
    global _GATEWAY
    _GATEWAY = None
