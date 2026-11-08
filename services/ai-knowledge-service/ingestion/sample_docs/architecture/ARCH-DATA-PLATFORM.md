---
doc_id: ARCH-DATA-PLATFORM
title: Data Platform and Knowledge Base Architecture
department: data
document_type: architecture
access_level: internal
created_date: 2025-11-12
version: 1.1
source_url: https://wiki.abcbank.internal/arch/data-platform
---

# Data Platform and Knowledge Base Architecture

## Knowledge Base
Organizational documents are chunked section-by-section, embedded, and upserted into a Pinecone
sparse-dense index. Each namespace holds one document type (policies, architecture, runbooks,
incidents, specs, meetings).

## Retrieval
Retrieval is hybrid: dense embeddings for semantic match plus BM25 sparse for exact terms and error
codes, fused with Reciprocal Rank Fusion and reranked by a cross-encoder.

## Metadata
Every chunk carries department, document_type, access_level, created_date, section, and source_url.
