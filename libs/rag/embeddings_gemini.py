"""Real semantic embeddings via Google Gemini (google-genai). Activated by
EMBEDDING_PROVIDER=gemini (+ GEMINI_API_KEY). Produces meaning-based vectors so the dense half of
the hybrid retriever ranks by *meaning*, complementing the BM25 *text* match. docs/04 §5, ADR-002.

Safety: the embedder probes once at construction; if Gemini embeddings aren't usable, get_embedder
falls back to the offline HashingEmbedder (consistent dimension). Vectors are L2-normalised so the
pipeline's dot-product cosine is exact.
"""
from __future__ import annotations

import math
import os


def _normalize(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / n for v in vec]


class GeminiEmbedder:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        from google import genai  # pip install google-genai

        self._genai = genai
        self._client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
        self.model = model or os.getenv("EMBEDDING_MODEL", "text-embedding-004")
        # probe once so a misconfig fails at construction (get_embedder then falls back to hashing)
        self._dim = len(self._raw_embed("probe"))

    def _raw_embed(self, text: str) -> list[float]:
        resp = self._client.models.embed_content(model=self.model, contents=(text or " ")[:8000])
        emb = resp.embeddings[0]
        return list(getattr(emb, "values", emb))

    def embed(self, text: str) -> list[float]:
        try:
            return _normalize(self._raw_embed(text))
        except Exception:
            # keep the dimension consistent so cosine/fusion don't break on a transient failure
            return [0.0] * self._dim
