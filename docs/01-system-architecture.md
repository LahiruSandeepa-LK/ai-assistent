# 01 — System Architecture

## 1. Architectural style

The system is a **monorepo of cooperating microservices**, each independently containerized
and composed with **Docker Compose**. Services communicate over HTTP/REST (sync request
path) and expose Server-Sent Events (SSE) for streaming. The AI "brain" is isolated in its
own service so it can be scaled, traced, and deployed independently of the web edge.

**Why microservices + monorepo (not a modular monolith, not polyrepo):**

- The brief explicitly asks for *microservice architecture, single repository, multiple
  services run with Docker*. We honor that literally.
- Different components have different runtime profiles: the **gateway** is I/O-bound and
  cheap; the **agent service** is latency-heavy and GPU/LLM-bound; the **MCP service** is a
  tiny data server. Independent scaling and failure isolation matter.
- A monorepo keeps shared contracts (Pydantic models, proto-like schemas, auth client,
  logging) in one place with atomic cross-service commits and one CI pipeline — avoiding the
  versioning tax of polyrepo for a small team. (ADR-007.)

## 2. Services (containers)

Canonical names are the **`ai-*` services** (full catalog, connection matrix and old-name
mapping in **`docs/13-service-topology.md`**).

| # | Service | Container | Tech | Responsibility |
|---|---------|-----------|------|----------------|
| 1 | **Public Assistant UI** | `ui-public` | Streamlit | **Interface 1** — chat + **Activity Panel**. All authenticated users. |
| 2 | **Admin Console UI** | `ui-admin` | Streamlit | **Interface 2** — doc mgmt, analytics. **Administrators only.** |
| 3 | **ai-assistant-api** | `ai-assistant-api` | FastAPI (async) | Chat edge: authN/RBAC, rate-limit, **token-budget gate**, input guardrail, SSE, correlation id |
| 4 | **ai-orchestrator** | `ai-orchestrator` | FastAPI + LangGraph | Intent **router**, multi-agent graph, RLM, tool selection, guardrails |
| 5 | **ai-knowledge-service** | `ai-knowledge-retrieval` + `ai-knowledge-ingest` | FastAPI (async) | RAG: retrieval read path (hybrid+rerank) + ingestion write path (chunk→embed→upsert) + document registry |
| 6 | **ai-tool-service** | `ai-tool-service` | MCP SDK | Tool registry + execution (MCP + external REST/DB), Python analysis sandbox |
| 7 | **ai-conversation-service** | `ai-conversation-service` | FastAPI (async) | History, context, short/long-term memory, **summarize-after-N**, **semantic cache**, **per-user token/usage state** |
| 8 | **ai-model-gateway** | `ai-model-gateway` | FastAPI (async) | Single entry for all LLM calls: provider routing + fallback + **token metering** |
| 9 | **ai-admin-service** | `ai-admin-service` | FastAPI (async) | Tool config, knowledge management, analytics + **accuracy eval** harness |
| 10 | **Keycloak** | `keycloak` | Keycloak | OIDC IdP, realm with 3 roles |
| 11 | **Redis** | `redis` | Redis | Checkpointer (short-term memory), cache, rate-limit buckets, **token-usage counters** |
| 12 | **Postgres** | `postgres` | Postgres | Long-term memory, feedback, audit, document registry, **token-usage ledger**, Keycloak store |

External managed dependencies: **Pinecone** (vector DB), **LangSmith** (tracing), **LLM
provider API** (Anthropic primary / OpenAI fallback, behind ai-model-gateway), **embedding API**.

> **Why ai-model-gateway?** Per-user **token budgets** are a hard requirement, so every LLM call
> funnels through one service that meters tokens, enforces cost caps, and does provider fallback —
> it can't be bypassed by any code path (ADR-010).
>
> **Why ai-conversation-service as its own service?** Everything per-user — history, memory,
> summarization, semantic cache, **token-budget counters** — lives in one place with one
> Redis/Postgres footprint (docs/13 §4, docs/14).
>
> **Why two front-end interfaces?** The Admin Console is a separate surface/container (its own
> backend, `ai-admin-service`), so admin capabilities — above all document management — have a
> different audience and attack surface and are Administrator-only; the public chat cannot reach
> the admin routes (ADR-009).
>
> **Why one knowledge service, two deployables?** `ai-knowledge-retrieval` (read) and
> `ai-knowledge-ingest` (write) share the vector DB + registry but run as separate processes, so
> re-indexing never contends with live query latency.

## 3. Request lifecycle (happy path)

> Service names below are the short/role labels; they map to the `ai-*` services in §2 and
> `docs/13`. The full flow with the **token-budget gate** and the **cache / answer-from-context
> skip paths** is in `docs/14` and `diagrams/request-flow-token-budget.drawio`.

```
                 ┌─────────┐   1. prompt + session_id (+ JWT)
   User ───────▶ │   UI    │ ───────────────────────────────┐
                 │Streamlit│ ◀── 9. SSE: tokens + activity ── │
                 └─────────┘                                  ▼
                                                      ┌───────────────┐
                                          2. validate │  API GATEWAY  │ 3. RBAC + rate limit (token bucket)
                                             JWT ◀────▶│   (FastAPI)   │────────────┐
                                                      └───────────────┘            │  4. forward (user ctx, roles)
                                                                                    ▼
                                                                         ┌─────────────────────┐
                                                                         │   AGENT SERVICE     │
                                                                         │   LangGraph graph   │
                                                                         │  Supervisor         │
                                                                         │   ├─ Retrieval ─────┼──┐ 5. hybrid search
                                                                         │   ├─ Research (RLM) │  │
                                                                         │   ├─ Validation     │  ▼
                                                                         │   └─ Response ──────┤  ┌──────────────┐
                                                                         └───────┬────┬────────┘  │  RETRIEVAL   │
                                                                     6. tool call │    │ memory     │  service     │
                                                                                  ▼    ▼            └──────┬───────┘
                                                                           ┌─────────┐ ┌────────┐          │ Pinecone
                                                                           │   MCP   │ │ Redis/ │          ▼ (dense+sparse)
                                                                           │ server  │ │Postgres│   ┌────────────┐
                                                                           └─────────┘ └────────┘   │  Pinecone  │
                                                                                                     └────────────┘
          every step ──────────────────────────────────────────────▶  LangSmith (traces)  ◀─── 8
```

1. User submits a message; UI holds `session_id` and the Keycloak access token.
2. Gateway validates the JWT (signature, expiry, audience) and extracts roles.
3. Gateway enforces **RBAC** (is this user allowed to use chat/search/tools?) and **token-bucket
   rate limiting** per user; invalid input is rejected with structured 4xx.
4. Gateway forwards to the Agent service with a signed internal context (user id, roles,
   correlation id). Roles are **never** taken from the model or the prompt.
5. The LangGraph **Supervisor** classifies intent and routes. Retrieval/Research agents call
   the Retrieval service for hybrid search; Pinecone returns scored, attributed chunks.
6. Tools (Knowledge Search, MCP, Python Analysis) execute asynchronously; the **tool policy
   enforcement point** re-checks the caller's role before each tool runs.
7. Memory is read at graph start and written at graph end (short-term via checkpointer,
   long-term summary into Postgres/vector memory).
8. Every node, tool, and retrieval call emits a LangSmith span under one run tree.
9. Tokens and **activity events** (agent state, active node, tool calls, retrieval status,
   memory updates, validation results) stream back to the UI over SSE.

## 3b. Admin document-management flow (Interface 2)

```
 Administrator ─▶ ui-admin (Streamlit) ─▶ gateway /admin/documents (Administrator-gated)
                                               │  1. authZ: role == Administrator (edge + PEP)
                                               ▼
                                         ingestion service  ── /ingest
                                               │  2. validate file (type, size, scan)
                                               │  3. section-aware chunk
                                               │  4. embed (dense) + sparse vectors
                                               ▼
                                         Pinecone (upsert into namespace + metadata)
                                               │  5. write doc registry row (status) → Postgres
                                               ▼
                                         ui-admin shows indexing status + KB browser
```

Only Administrators reach these routes (RBAC at the edge **and** the Policy Enforcement Point).
Document add/update/delete is audited, and every change updates the Postgres **document
registry** so the admin console can show what is indexed and its status. New/updated content is
immediately retrievable by the Public Assistant through the normal retrieval path.

## 4. Data flow and contracts

Internal services speak JSON over HTTP with shared **Pydantic** models (in `libs/contracts`).
Key payloads:

- `ChatRequest { session_id, message, stream: bool }`
- `AgentEvent { type: "node"|"tool"|"retrieval"|"memory"|"validation"|"token"|"final"|"error", ... }`
  — the single event envelope that powers both SSE streaming and the activity panel.
- `RetrievalRequest { query, filters, namespaces, top_k, rerank: bool }`
- `RetrievalResult { chunks: [{text, score, source{doc_id,title,section,url},
  dense_score, sparse_score, rerank_score}] }`
- `DocumentOp { op: "upsert"|"delete", doc_id, namespace, metadata, content? }` — admin
  document-management payload sent ai-admin-service → ai-knowledge-service (ingest).
- `IngestStatus { doc_id, status: "queued"|"chunking"|"embedding"|"indexed"|"failed", chunks }`
- `UsageCheck { user_id } → { remaining, limit, reset_at }` — ai-assistant-api → ai-conversation-service (token-budget pre-check).
- `UsageRecord { user_id, prompt_tokens, completion_tokens, model }` — ai-model-gateway → ai-conversation-service (post-call metering).
- `ContextBundle { summary, recent_turns, profile, cache_hit? }` — ai-conversation-service → ai-orchestrator.

The `AgentEvent` envelope is the backbone of the transparency requirement (FE4–FE11): the
graph emits one event per meaningful state change, the gateway relays it, the UI renders it.

## 5. Monorepo layout

```
ai-assistant/
├── docker-compose.yml                # all services (see 10-deployment.md)
├── docker-compose.dev.yml            # hardcoded-auth dev override, hot reload
├── Makefile                          # make dev / make up / make ingest / make test
├── .env.example
├── pyproject.toml                    # workspace tooling (ruff, mypy, pytest)
├── libs/                             # shared, versioned-in-place internal packages
│   ├── contracts/                    # Pydantic models, AgentEvent, error types
│   ├── authz/                        # JWT verify, RBAC policy, tool-permission map
│   ├── observability/                # logging config, LangSmith setup, correlation ctx
│   └── llm/                          # LLMProvider interface + Anthropic/OpenAI adapters
├── services/
│   ├── ui-public/                        # Interface 1 — Streamlit public assistant
│   ├── ui-admin/                         # Interface 2 — Streamlit admin console (Admin only)
│   ├── ai-assistant-api/                 # chat edge: auth, RBAC, rate-limit, TOKEN GATE, SSE
│   │   └── app/routes/{chat,admin}.py, app/middleware/
│   ├── ai-orchestrator/                  # LangGraph brain
│   │   └── app/graph/{state,build,edges}.py, graph/nodes/{router,supervisor,
│   │       retrieval_agent,research_agent_rlm,validation,response,hitl_approval}.py,
│   │       app/tools/, app/guardrails/
│   ├── ai-knowledge-service/             # RAG — one service, two deployables
│   │   ├── retrieval/  app/{hybrid,pinecone_store,embeddings}.py   # READ path
│   │   └── ingestion/  {ingest,cli}.py, app/main.py, sample_docs/  # WRITE path + /ingest API
│   ├── ai-tool-service/                  # tool registry + execution (MCP + external) + data/
│   ├── ai-conversation-service/          # history, memory, summarizer, cache, usage(token budget)
│   │   └── app/{history,memory_long,summarizer,cache,usage}.py
│   ├── ai-model-gateway/                 # all LLM calls: router+fallback + metering
│   │   └── app/{router,metering}.py
│   └── ai-admin-service/                 # admin backend: knowledge_admin, tool_config, analytics
│       ├── app/{knowledge_admin,tool_config,analytics}.py
│       └── eval/{run_eval.py, golden_set.sample.jsonl}   # accuracy harness (docs/15)
├── libs/                                 # contracts, authz, observability, llm
├── tests/                                # unit + integration + guardrails (red-team)
└── docs/ , diagrams/ , skills/           # design package alongside the code
```

> The router node is new (first node in the graph); `supervisor` now classifies *after* the
> router has ruled out cache/answer-from-context (docs/14 §2, docs/03).

Shared code in `libs/` is imported by services via local path installs, so a change to a
contract or the RBAC policy is one atomic commit across every consumer.

## 6. Scalability & reliability (overview — detail in 10 & 11)

- **Stateless services** (gateway, agent, retrieval) scale horizontally behind the Compose
  network; state lives in Redis/Postgres/Pinecone.
- **Short-term memory** uses a LangGraph checkpointer backed by Redis so any agent replica
  can resume a thread.
- **Degradation ladder** (detail in `11`): Pinecone down → sparse-only from cache; rerank
  down → skip rerank; LLM primary down → fallback provider; MCP down → circuit-break and
  answer from knowledge base with a note. The app always returns *something* truthful.
- **Backpressure** via token-bucket rate limiting at the edge protects the LLM budget and
  downstream services.

## 7. Cross-cutting concerns

| Concern | Mechanism | Doc |
|---|---|---|
| AuthN / AuthZ | Keycloak OIDC + `libs/authz` RBAC | `06` |
| Rate limiting | Token bucket in Redis (per-user, configurable) | `06`, ADR-008 |
| Observability | LangSmith run tree + structured JSON logs + `/metrics` | `07` |
| Config | 12-factor env vars, `.env`, Pydantic `Settings` | `10` |
| Errors | Shared error taxonomy in `libs/contracts`, graceful degradation | `11` |
| Memory | Redis checkpointer + Postgres/vector long-term | `05` |
| Tracing correlation | `X-Correlation-ID` propagated through every hop and into LangSmith metadata | `07` |
