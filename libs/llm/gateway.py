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


def get_gateway() -> ModelGateway:
    global _GATEWAY
    if _GATEWAY is None:
        # LLM_FALLBACK (e.g. "openai") gives provider resilience per ADR-003/E1.
        fallback = build_provider(os.getenv("LLM_FALLBACK", ""))
        _GATEWAY = ModelGateway(fallback=fallback)
    return _GATEWAY
