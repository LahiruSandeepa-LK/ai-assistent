"""Real OpenAI embeddings adapter. Activated by EMBEDDING_PROVIDER=openai (+ OPENAI_API_KEY).
Pairs with the Pinecone adapter for production-grade recall. text-embedding-3 vectors are
L2-normalised, so the dot-product `cosine()` in embeddings.py is exact. docs/04 §5, ADR-002.
"""
from __future__ import annotations

import os


class OpenAIEmbedder:
    """Embeds via the OpenAI embeddings API. Model + endpoint are env-overridable."""

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None):
        from openai import OpenAI  # pip install openai

        kw = {"api_key": api_key or os.environ["OPENAI_API_KEY"]}
        if base_url or os.getenv("OPENAI_BASE_URL"):
            kw["base_url"] = base_url or os.getenv("OPENAI_BASE_URL")
        self._client = OpenAI(**kw)
        self.model = model or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    def embed(self, text: str) -> list[float]:
        # OpenAI rejects empty input; guard, and cap length defensively.
        payload = (text or " ")[:8000]
        resp = self._client.embeddings.create(model=self.model, input=payload)
        return list(resp.data[0].embedding)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self.model, input=[t[:8000] or " " for t in texts])
        return [list(d.embedding) for d in resp.data]
