# 04 — RAG & Retrieval Architecture

> Covers **RAG Design (15%)** and bonus **Reranking layer (B3)**. Requirements R1–R9.

## 1. Principle

Retrieval quality is the single biggest lever on answer quality, so we implement **hybrid
search** (dense + sparse) with a **reranking** layer, grounded in **Pinecone**, and we
return **attributed, section-level** results so the agent can cite and the validator can
verify. Retrieval is its own service so it can be scaled, cached, and rate-limited
independently and reused by both the Retrieval and Research (RLM) agents.

## 2. Hybrid search pipeline

```
 query ──▶ ┌───────────────┐
           │ query analysis│ (clean, detect filters, expand acronyms)
           └──────┬────────┘
     ┌────────────┴─────────────┐
     ▼ (asyncio.gather)          ▼
┌──────────────┐          ┌──────────────┐
│ DENSE search │          │ SPARSE search│
│ embeddings   │          │ BM25 / sparse│
│ (Pinecone)   │          │ vectors      │
└──────┬───────┘          └──────┬───────┘
       │ top-N dense             │ top-N sparse
       └───────────┬─────────────┘
                   ▼
          ┌──────────────────┐
          │  FUSION (RRF)    │  reciprocal rank fusion of the two lists
          └────────┬─────────┘
                   ▼ top-K candidates
          ┌──────────────────┐
          │  RERANK layer    │  cross-encoder reranker (bonus B3)
          └────────┬─────────┘
                   ▼ top-k final
          ┌──────────────────┐
          │  ATTRIBUTION      │  attach doc_id, title, section, url, scores
          └────────┬─────────┘
                   ▼
            attributed chunks → agent
```

### 2.1 Dense search
Query is embedded with the embedding model; Pinecone returns nearest neighbors by cosine.
Good for semantic / paraphrased questions ("why did payments break?" ↔ "payment gateway
outage").

### 2.2 Sparse search (BM25)
Keyword/BM25-style sparse vectors. Good for exact terms, codes, acronyms, error strings
("ERR_CONN_POOL", "SOX", a specific service name) where embeddings are weak.

### 2.3 Hybrid ranking — Reciprocal Rank Fusion
We combine the two ranked lists with **RRF**:

```
score(d) = Σ  1 / (k + rank_i(d))         # k≈60, i ∈ {dense, sparse}
```

RRF is chosen over a weighted linear blend of raw scores because dense cosine and sparse BM25
scores are not on the same scale; RRF only needs ranks, is robust, and needs no per-query
tuning. A configurable `alpha` weighted blend is available as an alternative (ADR-004).

### 2.4 Reranking layer (bonus B3)
Top-K (≈30) fused candidates are re-scored by a **cross-encoder reranker** that reads
`(query, chunk)` jointly — far more precise than bi-encoder similarity. We keep the top-k
(≈6) for the context window. This is the biggest precision win and directly reduces
hallucination because the agent sees fewer, better chunks. Reranking is feature-flagged so it
can be skipped under load (degradation ladder, `11`).

## 3. Pinecone usage (R5–R9)

### 3.1 Index & hybrid
A single Pinecone **sparse-dense index** per environment, enabling native hybrid retrieval
(R8) without standing up a separate keyword engine for the POC. (Trade-off vs
OpenSearch/Elasticsearch in ADR-004.)

### 3.2 Namespaces (R6)
Namespaces partition the vector space for isolation and faster, scoped queries:

| Namespace | Contents |
|-----------|----------|
| `policies` | Company policies |
| `architecture` | Architecture documents |
| `runbooks` | Operational runbooks |
| `incidents` | Incident reports |
| `specs` | Product specifications |
| `meetings` | Meeting notes |

Namespaces also map to **access scope**: a Viewer's queries may be restricted to a subset of
namespaces (authorization shapes retrieval — see `06`).

### 3.3 Metadata filtering (R7)
Every chunk carries metadata, filterable server-side at query time:

```json
{
  "doc_id": "INC-2026-0421",
  "title": "Payment Gateway Timeout — 2026-04-21",
  "department": "payments",
  "document_type": "incident",
  "access_level": "internal",
  "created_date": "2026-04-21",
  "section": "Root Cause",
  "source_url": "https://wiki.internal/INC-2026-0421#root-cause"
}
```

This exactly matches the brief's metadata example (`department`, `document_type`,
`access_level`, `created_date`) and powers the RLM's cheap "explore the collection" step and
RBAC-aware filtering (never surface `access_level` above the user's clearance).

### 3.4 Document attribution (R9)
Each returned chunk includes `{doc_id, title, section, source_url, dense_score, sparse_score,
rerank_score}`. The Response agent renders inline citations; the Validation agent uses
`doc_id` to confirm no citation was hallucinated (S3).

## 4. Chunking & ingestion

- **Section-aware chunking:** split on document structure (headings) first, then size-bound
  (~500–800 tokens, ~15% overlap). Section-level chunks are what make RLM1 ("don't load whole
  docs") and targeted retrieval real.
- **Ingestion job** (`services/ingestion`): load mock corpus → section-chunk → embed (dense)
  + build sparse vectors → upsert to the right namespace with full metadata. Idempotent
  upserts keyed by `chunk_id = sha256(doc_id + section + ordinal)`.
- Mock corpus generator produces incident reports, runbooks, architecture docs, and product
  specs (brief's Sample Documents), with realistic metadata so retrieval and RLM can be
  demoed end-to-end.

## 5. Async & performance

- Dense and sparse queries run concurrently (`asyncio.gather`) — BE4.
- Query-embedding and frequent-query results are cached in Redis (TTL) to cut latency and
  embedding cost.
- Retrieval service exposes `/search` (async) returning `RetrievalResult` (contract in `01`).

## 6. Failure modes (feeds the degradation ladder in `11`)

| Failure | Behavior |
|---------|----------|
| Pinecone timeout/5xx | Retry w/ backoff; then serve from Redis cache; then sparse-only if available; else return "retrieval degraded" to the agent, which answers conservatively and says so |
| Embedding provider down | Fall back to sparse-only search |
| Reranker down/slow | Skip rerank, use RRF order (flagged in trace) |
| Empty results | Agent asks a clarifying question or states no evidence found — never fabricates |

## 7. Trade-offs

- **RRF vs learned fusion:** RRF is robust and tuning-free; a learned fusion could win a few
  points of recall but needs labeled data we don't have for the POC. Revisit with the
  feedback-loop dataset (`07`).
- **Pinecone-native hybrid vs dedicated BM25 engine:** native keeps the POC to one store;
  a dedicated engine (OpenSearch) would give richer lexical features at the cost of another
  service to run and secure. (ADR-004.)
