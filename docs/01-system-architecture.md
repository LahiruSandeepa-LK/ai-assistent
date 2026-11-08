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

| # | Service | Container | Tech | Responsibility |
|---|---------|-----------|------|----------------|
| 1 | **Public Assistant UI** | `ui-public` | Streamlit | **Interface 1** — chat window, streaming, **Agent Activity Panel** (transparency). All authenticated users. |
| 2 | **Admin Console UI** | `ui-admin` | Streamlit | **Interface 2** — document management, KB browser, feedback/audit review, observability links. **Administrators only.** |
| 3 | **API Gateway** | `gateway` | FastAPI (async) | AuthN/AuthZ enforcement, RBAC, rate limiting, input validation, SSE fan-out, request correlation. Serves both the public chat routes and the admin routes (admin routes Administrator-gated). |
| 4 | **Agent / Orchestration** | `agent` | FastAPI + LangGraph | The multi-agent graph, RLM, tool calling, guardrails, memory I/O, LangSmith tracing |
| 5 | **Retrieval** | `retrieval` | FastAPI (async) | Hybrid search, reranking, Pinecone client, embedding, document attribution |
| 6 | **Ingestion / Document mgmt** | `ingest` | FastAPI (async) + CLI | Chunk + embed + upsert into Pinecone (namespaces + metadata). Exposes an **internal `/ingest` API** the admin routes call to add/update/delete documents, plus a batch CLI for the initial mock corpus. |
| 7 | **MCP Server** | `mcp` | Python MCP SDK | Dummy enterprise data (employee directory, service catalog, incident records) |
| 8 | **Keycloak** | `keycloak` | Keycloak | OIDC identity provider, realm with 3 roles |
| 9 | **Redis** | `redis` | Redis | LangGraph checkpointer (short-term memory), rate-limit buckets, cache |
| 10 | **Postgres** | `postgres` | Postgres | Durable memory (long-term summaries), feedback, audit log, **document registry** (uploaded-doc metadata/status), Keycloak store |

External managed dependencies: **Pinecone** (vector DB), **LangSmith** (tracing), **LLM
provider API** (Anthropic primary / OpenAI fallback), **embedding API**.

> **Why two front-end interfaces?** Keeping the Admin Console a *separate surface and container*
> (not an "admin tab" in the public app) means admin capabilities — above all document
> management — have a different attack surface, a different audience, and Administrator-only
> access enforced at both the route and the role level. The public chat cannot even reach the
> admin routes. (ADR-009.)
>
> **Why split Retrieval from Agent?** Retrieval has a different scaling curve (CPU for BM25 +
> rerank, network for Pinecone), is reused by both the Retrieval agent and the RLM Research
> agent, and must be independently rate-limited and cached. Keeping it separate also lets us swap
> the vector store without touching the graph.
>
> **Why make Ingestion a service (not just a job)?** The admin "update documents" flow needs an
> on-demand API to chunk/embed/upsert a newly uploaded or edited document; the same code still
> runs as a batch CLI for the initial corpus.

## 3. Request lifecycle (happy path)

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
  document-management payload sent gateway → ingestion service.
- `IngestStatus { doc_id, status: "queued"|"chunking"|"embedding"|"indexed"|"failed", chunks }`

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
│   ├── ui-public/                    # Interface 1 — Streamlit public assistant
│   │   ├── app.py                    # chat window + streaming
│   │   ├── components/activity_panel.py
│   │   └── Dockerfile
│   ├── ui-admin/                     # Interface 2 — Streamlit admin console (Admin only)
│   │   ├── app.py                    # document mgmt, KB browser, feedback/audit, trace links
│   │   ├── components/doc_manager.py # upload / update / delete / reindex
│   │   └── Dockerfile
│   ├── gateway/
│   │   ├── app/main.py               # FastAPI, async, SSE
│   │   ├── app/routes/chat.py        # public chat routes
│   │   ├── app/routes/admin.py       # admin routes (Administrator-gated): documents, feedback, audit
│   │   ├── app/middleware/           # auth, rate_limit, validation, correlation
│   │   └── Dockerfile
│   ├── agent/
│   │   ├── app/graph/                # LangGraph: state.py, nodes/, edges.py, build.py
│   │   │   ├── nodes/supervisor.py
│   │   │   ├── nodes/retrieval_agent.py
│   │   │   ├── nodes/research_agent_rlm.py
│   │   │   ├── nodes/validation.py
│   │   │   ├── nodes/response.py
│   │   │   └── nodes/hitl_approval.py
│   │   ├── app/tools/                # knowledge_search, mcp_client, python_analysis
│   │   ├── app/guardrails/           # injection, output, citation, brand
│   │   ├── app/memory/               # short/long-term memory managers
│   │   └── Dockerfile
│   ├── retrieval/
│   │   ├── app/hybrid.py             # dense + sparse + RRF + rerank
│   │   ├── app/pinecone_store.py
│   │   ├── app/embeddings.py
│   │   └── Dockerfile
│   ├── mcp/                          # MCP server exposing dummy enterprise data
│   │   ├── server.py
│   │   ├── data/                     # employees.json, services.json, incidents.json
│   │   └── Dockerfile
│   └── ingestion/                    # document management + ingestion
│       ├── app/main.py               # FastAPI: internal /ingest API (add/update/delete/reindex)
│       ├── ingest.py                 # chunk → embed → upsert (namespaces + metadata)
│       ├── cli.py                    # batch load of the initial mock corpus
│       ├── sample_docs/              # generated mock corpus (incidents, runbooks, specs)
│       └── Dockerfile
├── tests/                            # unit + integration + guardrail red-team tests
└── docs/ , diagrams/ , .claude/      # this design package lives alongside the code
```

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
