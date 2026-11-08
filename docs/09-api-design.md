# 09 — API Design (Async FastAPI) & MCP

> Covers async engineering (BE1–BE7, Async 5%) and the tool/MCP surface (T1–T4).
> All handlers are `async def`; all downstream I/O (LLM, Pinecone, Redis, Postgres, MCP) uses
> async clients so a single worker handles many concurrent conversations.
>
> The gateway serves **two front ends**: the **Public Assistant** (`ui-public`) via the
> `/api/*` chat routes, and the **Admin Console** (`ui-admin`) via the `/admin/*` routes
> (Administrator-only, §1b).

## 1. Gateway API — public chat routes (`/api/*`)

### `POST /api/chat` — streaming chat (SSE)
Request:
```json
{ "session_id": "a1b2...", "message": "Summarize payment-failure outages last year", "stream": true }
```
Headers: `Authorization: Bearer <keycloak access token>`, `X-Correlation-ID` (optional; generated if absent).

Response: `text/event-stream` of `AgentEvent`s:
```
event: node        data: {"node":"supervisor","decision":"research"}
event: retrieval   data: {"status":"searching","namespaces":["incidents"],"candidates":37}
event: tool        data: {"tool":"knowledge_search","args_valid":true}
event: memory      data: {"op":"read","summary":"loaded 2 prior turns"}
event: token       data: {"text":"The most common root cause was "}
event: validation  data: {"verdict":"pass","citations_verified":5}
event: final       data: {"answer":"...","citations":[...],"trace_url":"https://smith.langchain.com/..."}
```

Behavior: auth → RBAC → rate limit (token bucket) → validate → proxy to agent → relay SSE.
Errors are structured (`4xx` validation/authz, `429` rate limit, `503` degraded) and also
surfaced as `event: error`.

### Other endpoints
| Method | Path | Purpose | Min role |
|--------|------|---------|----------|
| `POST` | `/api/chat` | Streaming chat | Viewer |
| `POST` | `/api/feedback` | 👍/👎 + comment on a turn (B5) | Viewer |
| `GET` | `/api/session/{id}/history` | Session transcript (from memory) | owner |
| `GET` | `/api/health` | Liveness/readiness | — |
| `GET` | `/metrics` | Prometheus metrics | internal |
| `GET` | `/api/me` | Resolved identity + roles (debug/transparency) | Viewer |

## 1b. Gateway API — admin routes (`/admin/*`, Administrator-only)

These power the **Admin Console** (`ui-admin`). Every route requires the `Administrator` role,
checked at the gateway edge **and** re-checked at the Policy Enforcement Point; every mutating
call is written to the audit log.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/admin/documents` | List indexed documents (from the document registry) + status |
| `POST` | `/admin/documents` | Upload a new document → validate → chunk → embed → upsert (`DocumentOp{op:"upsert"}`) |
| `PUT` | `/admin/documents/{doc_id}` | Replace/update a document and re-index it |
| `DELETE` | `/admin/documents/{doc_id}` | Remove a document and its vectors from Pinecone |
| `POST` | `/admin/documents/{doc_id}/reindex` | Re-chunk/re-embed an existing document |
| `GET` | `/admin/documents/{doc_id}/status` | Ingestion status (`IngestStatus`) |
| `GET` | `/admin/feedback` | Review 👍/👎 + comments (answer-quality) |
| `GET` | `/admin/audit` | Query the audit log (authz decisions, tool exec, refusals) |
| `GET` | `/admin/kb` | Browse namespaces + metadata facets |

Upload is `multipart/form-data` (file + `namespace` + `metadata`); the gateway streams it to the
ingestion service's internal `/ingest` API and returns an `IngestStatus` the console polls.

## 2. Agent service API (internal)

`POST /agent/run` — body includes the signed `UserContext` (id, roles), message, session_id.
Streams the same `AgentEvent`s back to the gateway. Never trusts roles from the request body
unless signed by the gateway's internal key.

## 3. Retrieval service API (internal)

`POST /search`:
```json
{ "query": "...", "namespaces": ["incidents"],
  "filters": {"department":"payments","document_type":"incident",
              "created_date":{"$gte":"2025-11-01"}},
  "top_k": 6, "rerank": true, "access_level_max": "internal" }
```
Returns `RetrievalResult` (attributed chunks with dense/sparse/rerank scores). Dense + sparse
run concurrently (`asyncio.gather`).

## 3b. Ingestion / Document-management service API (internal)

Called only by the gateway's admin routes (never exposed publicly).

`POST /ingest` — body `DocumentOp { op:"upsert"|"delete", doc_id, namespace, metadata, content? }`.
Async pipeline: validate → section-aware chunk → embed (dense) + sparse → upsert to Pinecone →
write/update the Postgres document registry. Returns `IngestStatus`. `GET /ingest/{doc_id}`
returns current status. A batch CLI entrypoint reuses the same pipeline for the initial mock
corpus.

## 4. MCP service (T2, T4)

A small **MCP server** exposing dummy enterprise data as MCP tools/resources:

| MCP tool | Returns | Min role |
|----------|---------|----------|
| `employee_directory.lookup` | Mock employee records | Analyst |
| `service_catalog.get` | Mock service metadata/owners | Analyst |
| `incident_records.query` | Mock incident records | Analyst |

The agent holds an **async MCP client**; the tool router invokes MCP tools when the Supervisor
decides they're needed and the PEP authorizes the caller. MCP calls are traced and have
timeouts + a circuit breaker (E3). (Brief marks MCP as lower priority; it is fully designed but
first to be trimmed if time runs short.)

## 5. Async & exception-handling patterns (BE2–BE7)

- **Async everywhere:** `async def` handlers, `httpx.AsyncClient`, `redis.asyncio`, async
  Pinecone calls, `asyncio.gather` for parallel retrieval, `asyncio.wait_for` for per-call
  timeouts.
- **Exception handling:** a shared error taxonomy (`libs/contracts.errors`): `ValidationError`
  (4xx), `AuthzError` (403), `RateLimitError` (429), `UpstreamError` (LLM/Pinecone/MCP → retry
  or degrade), `TimeoutError`. FastAPI exception handlers map each to a structured response and
  an `event: error`; nothing leaks a stack trace to the user.
- **Retries:** idempotent upstream calls use exponential backoff + jitter, capped, with a
  circuit breaker to avoid hammering a failing dependency (feeds the butterfly-effect controls
  in `03`).
- **Graceful degradation (E6):** on upstream failure the service returns a *partial but honest*
  result where possible (see the ladder in `11`), never a hard 500 with nothing.
- **Structured logging (BE7):** every handler logs entry/exit with correlation id and timing.

## 6. API trade-offs

- **SSE vs WebSocket:** SSE is simpler, works great with Streamlit and FastAPI for
  server→client token/event streaming, and is sufficient (we don't need bidirectional
  mid-stream). WebSocket revisited only if we add interactive mid-turn controls beyond HITL.
- **REST between services vs a message bus:** REST keeps the POC simple and debuggable; a bus
  (e.g., for async ingestion at scale) is a later evolution.
