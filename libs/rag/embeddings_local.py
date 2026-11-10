"""Local, offline semantic embeddings via fastembed (ONNX runtime, CPU, no torch).

Activated by EMBEDDING_PROVIDER=local. Model via LOCAL_EMBEDDING_MODEL (default
BAAI/bge-small-en-v1.5, 384-dim). Unlike a hosted embedding API this has NO key, NO per-day quota
and NO network calls after the model is cached, so you can embed the whole corpus (and re-embed on
restarts) for free. Vectors are L2-normalised so the pipeline's dot-product cosine is exact.
docs/04 §5, ADR-002."""
from __future__ import annotations

import math
import os


def _normalize(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / n for v in vec]


class LocalEmbedder:
    def __init__(self, model: str | None = None):
        from fastembed import TextEmbedding  # pip install fastembed

        self.model_name = model or os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        self._model = TextEmbedding(model_name=self.model_name)
        # probe once so a misconfig fails at construction (get_embedder then warns + falls back)
        self._dim = len(self._raw_embed("probe"))

    def _raw_embed(self, text: str) -> list[float]:
        # fastembed returns a generator of numpy arrays; take the first and cast to python floats
        vec = next(iter(self._model.embed([(text or " ")[:8000]])))
        return [float(x) for x in vec]

    def embed(self, text: str) -> list[float]:
        try:
            return _normalize(self._raw_embed(text))
        except Exception:
            # keep the dimension consistent so cosine/fusion don't break on a transient failure
            return [0.0] * self._dim
