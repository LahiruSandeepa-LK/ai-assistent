"""Google Gemini provider adapter.

Used when LLM_PROVIDER=gemini and GEMINI_API_KEY is set. Uses the google-genai SDK.
Model slugs change over time, so they are env-configurable — set GEMINI_MODEL_STRONG /
GEMINI_MODEL_FAST to the current models you have access to. ADR-003, ADR-010.
"""
from __future__ import annotations

import os

from .provider import BaseProvider, Completion

# "strong" for synthesis/validation, "fast" for routing/decomposition/summarise (docs/14 §2).
# Default to gemini-2.5-flash: generally available (incl. to new accounts) and low-latency. Model
# slugs are retired over time, so these are env-overridable AND the adapter self-heals to
# GEMINI_MODEL_FALLBACK on a NOT_FOUND / "no longer available" error.
_MODELS = {
    "strong": os.getenv("GEMINI_MODEL_STRONG", "gemini-3.8-flash"),
    "fast": os.getenv("GEMINI_MODEL_FAST", "gemini-3.8-flash"),
}
_FALLBACK_MODEL = os.getenv("GEMINI_MODEL_FALLBACK", "gemini-3.8-flash")


def _model_unavailable(err: Exception) -> bool:
    s = str(err).lower()
    return ("not_found" in s or "404" in s or "no longer available" in s
            or "not found" in s or "is not supported" in s)


class GeminiProvider(BaseProvider):
    is_mock = False
    name = "gemini"

    def __init__(self, api_key: str | None = None, model_strong: str | None = None,
                 model_fast: str | None = None, base_url: str | None = None):
        # base_url accepted for a uniform build signature; the google-genai SDK targets Google's
        # endpoint, so it is intentionally ignored here.
        from google import genai  # pip install google-genai

        key = api_key or os.environ["GEMINI_API_KEY"]
        self._genai = genai
        self._client = genai.Client(api_key=key)
        self._models = {
            "strong": model_strong or _MODELS["strong"],
            "fast": model_fast or _MODELS["fast"],
        }

    def _extract_text(self, resp) -> str:
        """Safely pull text out of a Gemini response. `resp.text` RAISES (not returns empty) when a
        response has no plain text part — e.g. a thinking model that spent its output budget on
        reasoning, or a non-STOP finish reason — so we must guard it and assemble from parts."""
        try:
            t = resp.text
            if t:
                return t.strip()
        except Exception:
            pass
        out = []
        for cand in getattr(resp, "candidates", []) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", []) or []:
                pt = getattr(part, "text", None)
                if pt:
                    out.append(pt)
        return "".join(out).strip()

    def complete(self, system: str, user: str, *, model: str = "strong") -> Completion:
        model_id = self._models.get(model, self._models["strong"])
        types = self._genai.types
        # GEMINI_THINKING_BUDGET caps "thinking" tokens for low latency. Some models (e.g. 2.5-pro)
        # reject budget 0; -1 leaves the model default.
        budget = int(os.getenv("GEMINI_THINKING_BUDGET", "0"))

        def _call(mid: str, use_thinking: bool):
            cfg = dict(system_instruction=system, temperature=0.2)
            if use_thinking and budget >= 0 and hasattr(types, "ThinkingConfig"):
                try:
                    cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=budget)
                except Exception:
                    pass
            return self._client.models.generate_content(
                model=mid, contents=user, config=types.GenerateContentConfig(**cfg))

        def _run(mid: str):
            try:
                r = _call(mid, use_thinking=True)
                t = self._extract_text(r)
            except Exception as e:
                if _model_unavailable(e):
                    raise  # let the caller self-heal to the fallback model
                r, t = None, ""
            if not t:
                r = _call(mid, use_thinking=False)   # retry without thinking cap
                t = self._extract_text(r)
            return r, t

        try:
            resp, text = _run(model_id)
        except Exception as e:
            # Self-heal: a configured model that was retired ("no longer available", 404) falls back
            # to a known-good model instead of erroring out to the mock provider.
            if _model_unavailable(e) and _FALLBACK_MODEL and _FALLBACK_MODEL != model_id:
                import sys
                print(f"[gemini] model '{model_id}' unavailable ({e}); retrying with "
                      f"'{_FALLBACK_MODEL}'", file=sys.stderr, flush=True)
                resp, text = _run(_FALLBACK_MODEL)
            else:
                raise
        um = getattr(resp, "usage_metadata", None)
        pt = getattr(um, "prompt_token_count", 0) or 0
        ct = getattr(um, "candidates_token_count", 0) or 0
        return Completion(text=text, prompt_tokens=pt, completion_tokens=ct)
