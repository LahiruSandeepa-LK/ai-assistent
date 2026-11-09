"""Model gateway: single entry for all LLM calls — provider routing + fallback +
token metering. ADR-010, docs/14."""
from __future__ import annotations

from typing import Callable, Optional

import os
import time

from .provider import BaseProvider, Completion, build_provider, get_provider

# How much of each prompt/response to log. Set LLM_LOG_FULL=true to log the complete text
# (otherwise previews are truncated to LLM_LOG_PREVIEW chars). docs/07.
_LOG_FULL = os.getenv("LLM_LOG_FULL", "false").lower() in ("1", "true", "yes")
_LOG_PREVIEW = int(os.getenv("LLM_LOG_PREVIEW", "500"))


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
        # over HTTP (which does its own metering + logging). Otherwise complete in-process.
        if os.getenv("MODEL_GATEWAY_URL"):
            from clients.services import remote_complete

            return remote_complete(system, user, model, user_id)

        from observability.logging import log

        provider_name = getattr(self.provider, "name", "?")
        t0 = time.time()
        # ---- log the LLM REQUEST ----
        log(self._log, "llm_request", provider=provider_name, model=model, user_id=user_id,
            system=_clip(system), prompt=_clip(user))
        try:
            c = self.provider.complete(system, user, model=model)
            used_provider = provider_name
        except Exception as e:
            # Resilience (ADR-003/E1): a provider failure (bad key, unavailable model, egress
            # blocked, rate limit) must not 500 the gateway. Log the real cause, then fall back to
            # the configured LLM_FALLBACK provider, and finally to the deterministic MockProvider
            # so chat always returns a grounded (if degraded) answer.
            import sys

            pname = getattr(self.provider, "name", "?")
            print(f"[model-gateway] provider '{pname}' failed for model '{model}': {e!r} — "
                  f"falling back", file=sys.stderr, flush=True)
            fb = self.fallback
            if fb is None:
                from .provider import MockProvider

                fb = MockProvider()
            try:
                c = fb.complete(system, user, model=model)
            except Exception:
                from .provider import MockProvider

                c = MockProvider().complete(system, user, model=model)
            used_provider = f"fallback:{getattr(fb, 'name', 'mock')}"
        # ---- log the LLM RESPONSE ----
        log(self._log, "llm_response", provider=used_provider, model=model, user_id=user_id,
            latency_ms=int((time.time() - t0) * 1000), prompt_tokens=c.prompt_tokens,
            completion_tokens=c.completion_tokens, response=_clip(c.text))
        if self.on_usage:
            try:
                self.on_usage(user_id, c.prompt_tokens, c.completion_tokens, model)
            except Exception:
                pass
        return c


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
