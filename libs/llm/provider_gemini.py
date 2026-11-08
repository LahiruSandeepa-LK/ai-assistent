"""Google Gemini provider adapter.

Used when LLM_PROVIDER=gemini and GEMINI_API_KEY is set. Uses the google-genai SDK.
Model slugs change over time, so they are env-configurable — set GEMINI_MODEL_STRONG /
GEMINI_MODEL_FAST to the current models you have access to. ADR-003, ADR-010.
"""
from __future__ import annotations

import os

from .provider import BaseProvider, Completion

# "strong" for synthesis/validation, "fast" for routing/decomposition/summarise (docs/14 §2)
# Durable aliases by default (model slugs change often); pin a concrete one via env, e.g.
# GEMINI_MODEL_STRONG=gemini-3.8-flash. Verified working: gemini-3.8-flash (2026-11).
_MODELS = {
    "strong": os.getenv("GEMINI_MODEL_STRONG", "gemini-pro-latest"),
    "fast": os.getenv("GEMINI_MODEL_FAST", "gemini-flash-latest"),
}


class GeminiProvider(BaseProvider):
    is_mock = False
    name = "gemini"

    def __init__(self):
        from google import genai  # pip install google-genai

        self._genai = genai
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def complete(self, system: str, user: str, *, model: str = "strong") -> Completion:
        model_id = _MODELS.get(model, _MODELS["strong"])
        types = self._genai.types
        cfg_kwargs = dict(system_instruction=system, temperature=0.2)
        # Gemini 3.x "thinks" by default, which adds latency. Cap it for low-latency grounded
        # synthesis; GEMINI_THINKING_BUDGET=-1 leaves the model default. Ignored by models that
        # don't support it.
        budget = int(os.getenv("GEMINI_THINKING_BUDGET", "0"))
        if budget >= 0 and hasattr(types, "ThinkingConfig"):
            try:
                cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=budget)
            except Exception:
                pass
        try:
            resp = self._client.models.generate_content(
                model=model_id, contents=user, config=types.GenerateContentConfig(**cfg_kwargs)
            )
        except Exception:
            # retry without thinking_config for models that reject it
            cfg_kwargs.pop("thinking_config", None)
            resp = self._client.models.generate_content(
                model=model_id, contents=user, config=types.GenerateContentConfig(**cfg_kwargs)
            )
        text = (resp.text or "").strip()
        um = getattr(resp, "usage_metadata", None)
        pt = getattr(um, "prompt_token_count", 0) or 0
        ct = getattr(um, "candidates_token_count", 0) or 0
        return Completion(text=text, prompt_tokens=pt, completion_tokens=ct)
