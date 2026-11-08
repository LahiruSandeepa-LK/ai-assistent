"""OpenAI provider adapter. LLM_PROVIDER=openai + OPENAI_API_KEY. ADR-003 (fallback)."""
from __future__ import annotations

import os

from .provider import BaseProvider, Completion

_MODELS = {
    "strong": os.getenv("OPENAI_MODEL_STRONG", "gpt-4.1"),
    "fast": os.getenv("OPENAI_MODEL_FAST", "gpt-4.1-mini"),
}


class OpenAIProvider(BaseProvider):
    is_mock = False
    name = "openai"

    def __init__(self):
        from openai import OpenAI  # pip install openai

        self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def complete(self, system: str, user: str, *, model: str = "strong") -> Completion:
        r = self._client.chat.completions.create(
            model=_MODELS.get(model, _MODELS["strong"]),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
        )
        text = (r.choices[0].message.content or "").strip()
        u = r.usage
        return Completion(text=text, prompt_tokens=u.prompt_tokens, completion_tokens=u.completion_tokens)
