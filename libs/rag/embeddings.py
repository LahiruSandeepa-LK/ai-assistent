"""Embeddings. Default = dependency-free deterministic hashing embedder (good enough
for a runnable POC + tests). Real providers plug in via EMBEDDING_PROVIDER. docs/04 §5."""
from __future__ import annotations

import hashlib
import math
import os
import re

_TOKEN = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class HashingEmbedder:
    """Hashes tokens into a fixed-dim L2-normalised vector. Deterministic, offline."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in tokenize(text):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def get_embedder():
    """Return the configured embedder. Falls back to HashingEmbedder offline."""
    provider = os.getenv("EMBEDDING_PROVIDER", "").lower()
    if provider in ("", "hashing", "local"):
        return HashingEmbedder()
    # Real provider hooks (only if deps + key are present). Each probes at construction; on any
    # failure we fall back to the offline HashingEmbedder so the index dimension stays consistent.
    try:  # pragma: no cover
        if provider == "openai":
            from .embeddings_openai import OpenAIEmbedder  # type: ignore

            return OpenAIEmbedder()
        if provider == "gemini":
            from .embeddings_gemini import GeminiEmbedder  # type: ignore

            return GeminiEmbedder()
    except Exception:
        pass
    return HashingEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
