"""Anthropic Claude provider adapter. LLM_PROVIDER=anthropic + ANTHROPIC_API_KEY. ADR-003."""
from __future__ import annotations

import os

from .provider import BaseProvider, Completion

_MODELS = {
    "strong": os.getenv("ANTHROPIC_MODEL_STRONG", "claude-sonnet-4-5"),
    "fast": os.getenv("ANTHROPIC_MODEL_FAST", "claude-haiku-4-5"),
}


class AnthropicProvider(BaseProvider):
    is_mock = False
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model_strong: str | None = None,
                 model_fast: str | None = None, base_url: str | None = None):
        import anthropic  # pip install anthropic

        kw = {"api_key": api_key or os.environ["ANTHROPIC_API_KEY"]}
        if base_url or os.getenv("ANTHROPIC_BASE_URL"):
            kw["base_url"] = base_url or os.getenv("ANTHROPIC_BASE_URL")
        self._client = anthropic.Anthropic(**kw)
        self._models = {"strong": model_strong or _MODELS["strong"],
                        "fast": model_fast or _MODELS["fast"]}

    def complete(self, system: str, user: str, *, model: str = "strong") -> Completion:
        msg = self._client.messages.create(
            model=self._models.get(model, self._models["strong"]),
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        u = msg.usage
        return Completion(text=text, prompt_tokens=u.input_tokens, completion_tokens=u.output_tokens)
