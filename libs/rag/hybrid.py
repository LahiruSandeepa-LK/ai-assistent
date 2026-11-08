"""Hybrid retrieval: dense + sparse -> RRF fusion -> optional rerank. docs/04 §2, ADR-004."""
from __future__ import annotations


def rrf_fuse(
    dense: list[tuple[str, float]],
    sparse: list[tuple[str, float]],
    k: int = 60,
) -> dict[str, float]:
    """Reciprocal Rank Fusion of two ranked lists of (chunk_id, score)."""
    scores: dict[str, float] = {}
    for ranked in (dense, sparse):
        for rank, (cid, _score) in enumerate(ranked):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return scores


def keyword_overlap_rerank(query: str, cid_text: dict[str, str], cids: list[str]) -> dict[str, float]:
    """Dependency-free stand-in for a cross-encoder reranker: Jaccard-ish overlap of
    query tokens with chunk tokens. Real deployments swap in a cross-encoder."""
    from .embeddings import tokenize

    q = set(tokenize(query))
    out: dict[str, float] = {}
    for cid in cids:
        toks = set(tokenize(cid_text.get(cid, "")))
        if not toks:
            out[cid] = 0.0
            continue
        out[cid] = len(q & toks) / (len(q) or 1)
    return out
