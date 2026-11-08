# Mock Knowledge Base — ABC Bank (fictional)

20 mock documents across 6 namespaces, generated to test **chunking** and **hybrid retrieval**.
All content is invented; ABC Bank is a fictional example company. See `MANIFEST.csv` for the index.

## Layout (namespace = document_type)
- `policies/`      data classification, access control/RBAC, incident management
- `architecture/`  payments platform, auth, data platform / knowledge base
- `runbooks/`      payment gateway, DB failover, TLS cert rotation
- `incidents/`     payment-failure incidents across a year + one unrelated login outage
- `specs/`         instant transfer, mobile statements
- `meetings/`      payments reliability review, architecture review

## What it is designed to exercise
- **Sparse / BM25 path:** exact tokens & error codes — `ERR_CONN_POOL`, `HTTP 504`, `HTTP 503`,
  `POOL_MAX`, CN `gateway.cardnet.abcbank`, doc IDs like `INC-2026-0121`.
- **Dense / semantic path:** paraphrasable prose (e.g. "why did payments break?" ↔ "upstream
  timeout / pool exhaustion").
- **Section-aware chunking:** every doc has multiple headings (Summary / Root Cause / Resolution,
  etc.) plus a Markdown **table** (data-classification, payments architecture) to test table-aware
  chunking.
- **Metadata filtering & RBAC:** `access_level` ranges public→confidential; `department`,
  `document_type`, `created_date` for filtered retrieval.
- **RLM / multi-hop demo:** the payment-failure incidents cluster into **recurring root causes** —
  gateway timeout (INC-2025-1103, INC-2026-0304), expired certificate (INC-2025-1219,
  INC-2026-0608), DB pool exhaustion (INC-2026-0121, INC-2026-0421) — so the
  "summarize outage reports and find recurring root causes" example works end to end.

## Load it
`make ingest`  (runs the ai-knowledge-ingest CLI over this folder → Pinecone namespaces).
