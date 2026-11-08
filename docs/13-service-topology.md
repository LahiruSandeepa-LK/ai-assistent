# 13 — Service Topology (ai-* services) & Connections

This is the canonical service map after the brainstorm. It supersedes the short service names
used earlier in `01` prose; the mapping is in §3. Diagrams:
`diagrams/service-connection-map.drawio`, `diagrams/c4-l2-container.drawio`.

## 1. The three intelligence capabilities → services

| Capability | What it does | Service |
|-----------|--------------|---------|
| **LLM — reasoning** | understand intent, extract params, plan, generate | **ai-orchestrator** (calls **ai-model-gateway**) |
| **RAG — knowledge** | search docs/policies/metadata | **ai-knowledge-service** |
| **API tools — actions** | call backend REST/DB/microservices/external | **ai-tool-service** |

The orchestrator is the only service that decides *which* capability a turn needs (the router).

## 2. Service catalog

| Service | Port | Responsibility | Talks to |
|---------|------|----------------|----------|
| **ui-public** | 8501 | Chat window + agent activity panel (Streamlit) | ai-assistant-api |
| **ui-admin** | 8502 | Admin console (Streamlit) | ai-admin-service |
| **ai-assistant-api** | 8000 | Chat API, authN/RBAC, rate-limit, **token-budget gate**, input guardrail, SSE streaming, correlation id | ai-orchestrator, ai-conversation-service, keycloak, redis |
| **ai-orchestrator** | 8100 | Intent **router**, LangGraph agents, RLM, tool selection, guardrails | ai-knowledge-service, ai-tool-service, ai-conversation-service, ai-model-gateway |
| **ai-knowledge-service** | 8200 (read) / 8400 (write) | RAG: `retrieval/` read path (hybrid+rerank) + `ingestion/` write path (chunk→embed→upsert) + document registry | pinecone, embeddings, postgres |
| **ai-tool-service** | 8300 | Tool registry + execution (MCP + external REST/DB), Python analysis sandbox | external APIs |
| **ai-conversation-service** | 8600 | History, context, short/long-term memory, **summarize-after-N**, **semantic cache**, **per-user token/usage state** | redis, postgres |
| **ai-model-gateway** | 8700 | Single entry for all LLM calls: provider routing + fallback + **token metering** | LLM providers, redis |
| **ai-admin-service** | 8800 | Tool config, knowledge management, analytics + **accuracy eval** harness | ai-knowledge-service (ingest), ai-tool-service, postgres, langsmith |
| keycloak / redis / postgres / pinecone | — | identity / fast state / durable state / vectors | — |

> **ai-knowledge-service is one logical service, two deployables** (`ai-knowledge-retrieval`,
> `ai-knowledge-ingest`) sharing the vector DB + registry, so re-indexing never contends with
> live query latency (my earlier "split read/write" note, realized physically).

## 3. Connection matrix (who calls whom, and how)

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| ui-public | ai-assistant-api | HTTPS + SSE | chat, stream tokens+events |
| ui-admin | ai-admin-service | HTTPS | admin ops |
| ai-assistant-api | keycloak | OIDC/JWKS | validate token → roles |
| ai-assistant-api | ai-conversation-service | REST | **token-budget pre-check** + user state |
| ai-assistant-api | redis | — | rate-limit buckets |
| ai-assistant-api | ai-orchestrator | REST + SSE | run a turn |
| ai-orchestrator | ai-conversation-service | REST | load context (summary+turns+profile) + **cache hit?**; write turns |
| ai-orchestrator | ai-knowledge-service (retrieval) | REST | hybrid search |
| ai-orchestrator | ai-tool-service | REST/MCP | execute tools (authz checked in code) |
| ai-orchestrator | ai-model-gateway | REST | **all LLM calls** |
| ai-model-gateway | LLM providers | HTTPS | completions/tool-use |
| ai-model-gateway | ai-conversation-service | REST | **report actual token usage** (post-call) |
| ai-knowledge-service | pinecone / embeddings | HTTPS | query/upsert, embed |
| ai-knowledge-service (ingest) | postgres | — | document registry |
| ai-conversation-service | redis / postgres | — | short-term+cache+usage / long-term+ledger |
| ai-admin-service | ai-knowledge-service (ingest) | REST | upload/update/delete/reindex |
| ai-admin-service | ai-tool-service | REST | tool configuration |
| ai-admin-service | postgres / langsmith | — | analytics / eval |
| all services | langsmith | HTTPS | traces (span tree) |
| all services | (OpenTelemetry collector) | — | distributed service-hop traces |

## 4. Why these boundaries

- **ai-conversation-service pulled out as its own service** (was memory-in-agent): everything
  per-user — history, memory, summarization, semantic cache, **token budget** — lives in one
  place with one Redis/Postgres footprint.
- **ai-model-gateway added**: because per-user token budgets are a hard requirement, routing
  every LLM call through one service gives a single point for token metering, cost caps, and
  provider fallback (ADR-010). The orchestrator no longer talks to providers directly.
- **ai-admin-service separated from ai-assistant-api**: admin surface (document management,
  analytics, eval) has a different audience and attack surface than the public chat (ADR-009).

## 5. Mapping from earlier short names

| Earlier (docs 01–12 prose) | Canonical service |
|---|---|
| gateway | ai-assistant-api |
| agent | ai-orchestrator |
| retrieval + ingestion | ai-knowledge-service (retrieval/ + ingestion/) |
| mcp / tool | ai-tool-service |
| memory (inside agent) | ai-conversation-service |
| (LLM called directly) | ai-model-gateway |
| ui-admin backend | ai-admin-service |

## 6. Tracing across services

Every request carries **`correlation_id` + `session_id` + `user_id`** from ai-assistant-api
through every hop. Two complementary traces: **LangSmith** for the orchestrator's reasoning/
tool/retrieval spans, and **OpenTelemetry** for the service-to-service hops (api→orchestrator→
knowledge/tool/model-gateway). One id ties a UI event, the service logs, and both traces together.
