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

    def __init__(self):
        import anthropic  # pip install anthropic

        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def complete(self, system: str, user: str, *, model: str = "strong") -> Completion:
        msg = self._client.messages.create(
            model=_MODELS.get(model, _MODELS["strong"]),
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        u = msg.usage
        return Completion(text=text, prompt_tokens=u.input_tokens, completion_tokens=u.output_tokens)
