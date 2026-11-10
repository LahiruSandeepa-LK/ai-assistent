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
    """Return the configured embedder. Falls back to HashingEmbedder offline.

    IMPORTANT: when a real provider is configured (EMBEDDING_PROVIDER=gemini/openai) but fails to
    construct — e.g. the EMBEDDING_MODEL is 404 for the key — we fall back to HashingEmbedder so the
    pipeline keeps working, but we LOG IT LOUDLY. A silent fallback once turned "semantic" dense
    retrieval into keyword-hash without anyone noticing, which badly hurt recall. docs/04 §5."""
    import sys

    provider = os.getenv("EMBEDDING_PROVIDER", "").lower()
    if provider in ("", "hashing", "hash"):
        return HashingEmbedder()
    # Real provider hooks (only if deps + key are present). Each probes at construction.
    try:  # pragma: no cover
        if provider in ("local", "fastembed", "st", "sentence-transformers"):
            from .embeddings_local import LocalEmbedder  # type: ignore

            return LocalEmbedder()
        if provider == "openai":
            from .embeddings_openai import OpenAIEmbedder  # type: ignore

            return OpenAIEmbedder()
        if provider == "gemini":
            from .embeddings_gemini import GeminiEmbedder  # type: ignore

            return GeminiEmbedder()
        print(f"[embeddings] unknown EMBEDDING_PROVIDER={provider!r} — using offline HashingEmbedder",
              file=sys.stderr, flush=True)
    except Exception as e:
        model = os.getenv("EMBEDDING_MODEL", "")
        print(f"[embeddings] WARNING: EMBEDDING_PROVIDER={provider!r} (model={model!r}) failed to "
              f"initialise ({e!r}) — DEGRADING to offline HashingEmbedder. Dense retrieval will be "
              f"keyword-hash, not semantic. Fix EMBEDDING_MODEL (list models that support "
              f"embedContent) and re-ingest.", file=sys.stderr, flush=True)
    return HashingEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
