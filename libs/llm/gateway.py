"""Model gateway: single entry for all LLM calls — provider routing + fallback +
token metering. ADR-010, docs/14."""
from __future__ import annotations

from typing import Callable, Optional

import os

from .provider import BaseProvider, Completion, build_provider, get_provider


class ModelGateway:
    def __init__(self, provider: Optional[BaseProvider] = None, fallback: Optional[BaseProvider] = None):
        self.provider = provider or get_provider()
        self.fallback = fallback
        # metering hook: fn(user_id, prompt_tokens, completion_tokens, model)
        self.on_usage: Optional[Callable[[str, int, int, str], None]] = None

    def complete(self, system: str, user: str, *, model: str = "strong", user_id: str = "") -> Completion:
        from observability.tracing import traced

        return traced(name="llm.complete", run_type="llm")(self._complete)(system, user, model=model, user_id=user_id)

    def _complete(self, system: str, user: str, *, model: str = "strong", user_id: str = "") -> Completion:
        try:
            c = self.provider.complete(system, user, model=model)
        except Exception:
            if not self.fallback:
                raise
            c = self.fallback.complete(system, user, model=model)
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
