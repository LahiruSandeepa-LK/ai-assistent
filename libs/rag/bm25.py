"""Minimal BM25 (Okapi) — dependency-free sparse retrieval. docs/04 §2.2."""
from __future__ import annotations

import math
from collections import Counter

from .embeddings import tokenize


class BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: list[list[str]] = []
        self.ids: list[str] = []
        self.df: Counter = Counter()
        self.idf: dict[str, float] = {}
        self.avgdl: float = 0.0

    def fit(self, corpus: list[tuple[str, str]]) -> "BM25":
        """corpus = list of (chunk_id, text)."""
        self.ids = [cid for cid, _ in corpus]
        self.docs = [tokenize(t) for _, t in corpus]
        self.df = Counter()
        for toks in self.docs:
            for tok in set(toks):
                self.df[tok] += 1
        n = len(self.docs) or 1
        self.idf = {
            tok: math.log(1 + (n - dfi + 0.5) / (dfi + 0.5)) for tok, dfi in self.df.items()
        }
        self.avgdl = (sum(len(d) for d in self.docs) / n) if self.docs else 0.0
        return self

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        q = tokenize(query)
        scores: list[tuple[str, float]] = []
        for cid, toks in zip(self.ids, self.docs):
            if not toks:
                continue
            tf = Counter(toks)
            dl = len(toks)
            s = 0.0
            for term in q:
                if term not in tf:
                    continue
                idf = self.idf.get(term, 0.0)
                denom = tf[term] + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                s += idf * (tf[term] * (self.k1 + 1)) / (denom or 1)
            if s > 0:
                scores.append((cid, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
