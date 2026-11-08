# ADR-004: Hybrid retrieval with RRF fusion + cross-encoder reranking

**Status:** Accepted · **Date:** 2026-11-08 · **Deciders:** AI Lead

## Context
Answer quality depends on retrieval precision. The brief requires hybrid search (dense +
sparse) with hybrid ranking; reranking is a bonus. We must combine two score distributions that
are not comparable and keep the final context small.

## Decision
Run **dense and sparse concurrently**, fuse with **Reciprocal Rank Fusion (RRF)**, then apply a
**cross-encoder reranker** and keep top-k sections. Fusion and rerank are feature-flagged.

## Options Considered
### Option A: RRF fusion + cross-encoder rerank (chosen)
**Pros:** RRF needs only ranks (robust, no per-query tuning across incomparable scores);
cross-encoder gives the biggest precision gain and cuts hallucination by shrinking context.
**Cons:** rerank adds latency/cost (mitigated by flag + top-K cap).

### Option B: Weighted linear blend (`alpha*dense + (1-alpha)*sparse`)
**Pros:** simple, one knob. **Cons:** needs score normalization + per-corpus tuning; brittle.
Kept as a configurable alternative.

### Option C: Dense-only
**Pros:** simplest. **Cons:** fails on exact terms/codes/acronyms; doesn't meet hybrid
requirement.

### Dedicated BM25 engine (OpenSearch) vs Pinecone-native sparse
Pinecone-native sparse keeps the POC to one store; OpenSearch gives richer lexical features but
another service to run/secure. Chose native for the POC.

## Trade-off Analysis
RRF + rerank maximizes precision per engineering hour and is robust without labeled data.
Latency is controlled with flags and candidate caps.

## Consequences
- Easier: high-precision, attributed context; fewer hallucinations.
- Harder: an extra model (reranker) to host/call; latency budget management.
- Revisit: learned fusion once the feedback dataset exists; OpenSearch if lexical needs grow.

## Action Items
1. [ ] `asyncio.gather` dense+sparse; RRF; reranker; attribution payload.
2. [ ] Flags: `rerank`, `fusion=rrf|alpha`; expose scores in traces.
