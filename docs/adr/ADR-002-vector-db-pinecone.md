# ADR-002: Use Pinecone as the vector database

**Status:** Accepted · **Date:** 2026-11-08 · **Deciders:** AI Lead, Platform

## Context
We need a vector database supporting namespaces, metadata filtering, hybrid (dense+sparse)
retrieval, and document attribution. The brief mandates Pinecone.

## Decision
Use **Pinecone** with a sparse-dense index, one namespace per document type, and rich metadata
(`department`, `document_type`, `access_level`, `created_date`, `section`, `source_url`).

## Options Considered
### Option A: Pinecone (managed)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low (managed) |
| Cost | $ (managed) |
| Scalability | High |
| Team familiarity | Good |

**Pros:** mandated; managed hybrid, namespaces, metadata; no ops. **Cons:** external
dependency; data-residency considerations for a conservative enterprise.

### Option B: pgvector / Qdrant / Weaviate (self-host)
**Pros:** data stays in-cluster; no vendor lock-in. **Cons:** ops burden; not mandated;
hybrid/rerank need more wiring for the POC.

## Trade-off Analysis
Pinecone removes retrieval-infra ops so the team spends time on agent/RAG quality (the heavily
graded parts). Vendor dependency is mitigated by isolating it behind the Retrieval service.

## Consequences
- Easier: hybrid retrieval, namespaces, metadata filters, scaling.
- Harder: data-residency story for production (note for a regulated enterprise deployment).
- Revisit: self-hosted store if residency/cost demands it — swap behind `pinecone_store.py`.

## Action Items
1. [ ] Provision sparse-dense index; define namespaces + metadata schema.
2. [ ] Abstract behind a `VectorStore` interface in the retrieval service.

## Implementation status (2026-11-09)
Implemented as a drop-in adapter behind one interface (`libs/rag/vectorstore.py` →
`get_vector_store()`). `libs/rag/vectorstore_pinecone.py` provides the real `PineconeVectorStore`
(modern `pinecone` SDK): lazy index creation at the live embedding dimension, cosine metric,
optional namespace (`PINECONE_NAMESPACE`), batched upserts, and reliable delete-by-`doc_id`
(id tracking with a metadata-filter fallback for pod indexes). Activates automatically when
`PINECONE_API_KEY` is set; the in-memory cosine index remains the offline default. The engine
code is unchanged — only the store swaps.
