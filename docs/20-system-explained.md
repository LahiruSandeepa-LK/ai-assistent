# 20 — The System Explained (a teaching guide)

> Audience: a software intern learning from an AI/ML systems lecturer. This walks through the
> **concepts**, the **workflows**, and the **code** of the ABC Bank AI Assistant, and — just as
> importantly — the *why* behind each decision.

---

## Part 1 — The big picture: what are we building, and why this way?

We are building an **enterprise AI assistant** that answers questions from an organization's own
knowledge (bank policies, product info, incidents, procedures). The headline idea:

> Don't just connect an LLM to a vector database. Build an **agentic RAG system** with the
> engineering a real company needs: security, observability, resilience, and clean architecture.

Two terms to internalize first:

- **LLM (Large Language Model)** — a model (here, Google Gemini) that generates text. On its own it
  "knows" only what it was trained on, it can't see your private documents, and it will confidently
  make things up (*hallucinate*).
- **RAG (Retrieval-Augmented Generation)** — before asking the LLM, we **retrieve** the most
  relevant passages from our own documents and put them in the prompt. The LLM then answers *from
  that evidence*. This grounds answers in real data and lets us **cite sources**.

"**Agentic**" means the system doesn't do a single fixed retrieve-then-answer step. It *decides*:
Is this a greeting? A follow-up? A simple lookup? A broad research question needing several
searches? Does it need a tool (a live lookup) instead of documents? That decision-making loop is
the "agent".

---

## Part 2 — Core concepts (the ML/IR foundations)

### 2.1 Embeddings and semantic search
An **embedding** is a vector (list of numbers) that represents the *meaning* of a piece of text.
Texts with similar meaning have vectors that point in similar directions. We measure closeness with
**cosine similarity** (the dot product of unit-length vectors). So "what's the home loan rate?" and
"mortgage interest" land near each other even with no shared words. This is **semantic search —
search by meaning**.

In code: `libs/rag/embeddings.py`. We have three embedders:
- `HashingEmbedder` — a dependency-free, offline vector (hashes tokens into a fixed-size vector).
  Deterministic and free, but only a rough sense of meaning. Good for demos/tests.
- `OpenAIEmbedder` / `GeminiEmbedder` — call a real model (`text-embedding-*`) for *true* semantic
  vectors. Enabled with `EMBEDDING_PROVIDER=openai|gemini`.

### 2.2 Keyword search (BM25)
Semantic search can miss exact tokens — an account number, a date like `2026-01-21`, a product code
`INC-2025-1219`. **BM25** is the classic *lexical* ranking function: it scores documents by exact
term overlap, weighting rare terms higher. This is **search by text similarity**. Code:
`libs/rag/bm25.py`.

### 2.3 Hybrid retrieval + fusion + rerank (the heart of accuracy)
Semantic and keyword search have complementary strengths, so we run **both** and combine them:

1. **Dense** (semantic) returns its top matches.
2. **Sparse** (BM25) returns its top matches.
3. **Reciprocal Rank Fusion (RRF)** merges the two ranked lists: each document scores
   `Σ 1/(k + rank)` across the lists, so items ranked highly by *either* method float up. RRF is
   robust because it uses *ranks*, not raw scores (which aren't comparable between the two methods).
4. **Rerank** — a final pass re-orders the fused candidates by closeness to the query (here, a
   keyword-overlap stand-in for a cross-encoder).
5. **Access filter** — drop chunks the user's role may not see (see RBAC).
6. Keep the **top 5** chunks and send only those to the LLM.

Code: `libs/rag/hybrid.py` (`rrf_fuse`, `keyword_overlap_rerank`) and `libs/rag/store.py`
(`KnowledgeIndex.search`). *Why top-5?* The LLM reasons better over a few highly-relevant passages
than over a large noisy context — and it's cheaper and faster.

### 2.4 Chunking
Documents are too big to embed whole, and we want to retrieve *passages*. **Chunking** splits a
document into overlapping, section-aware pieces. We prepend a small metadata header
(`doc_id | title | date | section`) to each chunk's indexed text so queries that mention a date or
ID still match. Code: `libs/rag/chunking.py`. This one detail fixed a real bug where date-specific
questions ranked the wrong incident.

### 2.5 Grounding, citations, and anti-hallucination
After retrieval, we build a prompt: *"Answer this QUESTION using ONLY this CONTEXT."* The LLM must
cite each fact with a `[DOC_ID]` marker. We then **verify** every citation exists in the retrieved
set (`guardrails.check_citations`) and measure **groundedness** (how much of the answer's
vocabulary appears in the context). The markers are stripped before the user sees the reply, and we
show friendly source *titles* instead. Code: `libs/orchestrator/guardrails.py`,
`libs/orchestrator/ops.py` (`synthesize`).

### 2.6 The agent loop and "RLM"
The **supervisor/router** classifies each question into a route: `greeting | context | retrieval |
research | tool`. A broad question ("summarize all payment outages last year") triggers a
**Recursive Language Model (RLM)** style flow: *decompose* the question into sub-questions, retrieve
for each in parallel (fan-out), then *aggregate* and synthesize. This is "plan-as-code". Code:
`libs/orchestrator/ops.py` (`classify`, `decompose`) and `graph_langgraph.py`.

### 2.7 Conversation memory (done carefully)
Naively feeding the whole chat history to the LLM every turn is wasteful and leaks context across
unrelated sessions. Our design:
- **Sessions are isolated**: a new session starts fresh; no prior history is fed to the agent.
- **Memory-as-RAG**: for follow-ups, we retrieve only the *relevant* prior turns *in the current
  session* (`relevant_turns`) and inject just those.
- **History is for the human**: the UI shows the user's last 3 sessions as read-only transcripts
  (via `/api/history`) — never sent to the model.
Code: `libs/memory/conversation.py`.

---

## Part 3 — Orchestration: LangGraph (the agent engine)

**LangGraph** models the agent as a **state graph**: nodes are steps (supervisor, retrieval, plan,
sub-retrieve, aggregate, tool, approval, respond) and edges are transitions, some *conditional*
(the router picks the next node). Key features we use:
- **Checkpointer** — persists state per conversation thread.
- **Conditional edges** — the router decides the path.
- **`Send` fan-out** — launch parallel sub-retrievals for RLM.
- **`interrupt`** — human-in-the-loop approval for sensitive actions.

Code: `libs/orchestrator/graph_langgraph.py`. There's also a **dependency-free fallback**
(`graph.py` `_pipeline_core`) that runs the exact same `ops.*` steps without LangGraph — so the
system still works if the library is absent, and tests run fast. The two share `libs/orchestrator/
ops.py`, so behaviour is identical. *Lesson: separate the business steps (ops) from the engine
(LangGraph) so you can swap or fall back.*

---

## Part 4 — The architecture: a microservice monorepo

**Monorepo** = one repository, many services, a shared engine. The engine lives in `libs/`
(pure-Python, unit-tested, no web framework). Each service in `services/` is a thin FastAPI (or
Streamlit) wrapper that imports `libs/`.

```
Browser ──WebSocket──> ui-public (Streamlit)
                           │ httpx (server-side)
                           ▼
                     ai-assistant-api ──HTTP──> ai-orchestrator ──HTTP──> ai-knowledge-retrieval  (/search)
                     (auth, RBAC,                (LangGraph brain)   ├──> ai-tool-service          (/call: MCP, web, docparser)
                      rate-limit,                                    ├──> ai-model-gateway         (/complete -> Gemini)
                      token budget)                                  └──> (conversation state in Postgres)
     admin console ──> ai-admin-service (uploads, LLM config)        Redis: budget/cache/rate-limit
     Keycloak: identity        Postgres: history/jobs/docs           Pinecone (optional): vectors
```

**Why microservices?** Each concern scales and fails independently; the LLM gateway, retrieval, and
tools can be deployed and secured separately. The trick: business logic stays in `libs/`, so a
service can run the orchestrator **in-process** (simple) or **over HTTP** (`*_URL` env set) with the
*same code*. Code: `libs/clients/services.py` is the HTTP seam.

---

## Part 5 — Walk the request lifecycle (follow one question end-to-end)

A customer asks *"What's the interest rate on a home loan?"*

1. **UI → API.** `ui-public` sends the message + the session id + the user's bearer token to
   `ai-assistant-api /api/chat` (server-side, so the browser never sees the internal calls).
2. **Security gate (API edge).** `ai-assistant-api/app/main.py`: authenticate the token
   (`authz/identity.py`), check the role may chat (`authz/rbac.py`), apply **rate limiting**
   (Redis fixed-window), and a **token-budget** pre-check (Redis counter). Any failure returns a
   clean error, never a crash.
3. **Delegate to the orchestrator** over HTTP (`ORCHESTRATOR_URL`), or run it in-process offline.
4. **Input guardrail.** `guardrails.screen_input` blocks prompt-injection attempts.
5. **Greeting / cache / route.** Greetings get a canned welcome (no LLM). A **semantic cache**
   (Redis) returns a prior answer if the question is ~identical. Otherwise the **router** classifies
   the route.
6. **Retrieve.** `tools.knowledge_search` → `KnowledgeIndex.search`: hybrid dense+BM25, RRF, rerank,
   access-filter, top-5. If the retrieval *service* is down, it degrades to the in-process index.
7. **Synthesize.** `ops.synthesize` builds the grounded prompt and calls the **model gateway**
   (`ai-model-gateway /complete`), which calls **Gemini**. The gateway meters tokens (Redis), logs
   the request/response, and — if Gemini fails — **falls back** to another provider or the mock, so
   the user always gets an answer.
8. **Validate + clean.** Verify citations, strip internal markers, attach friendly source titles.
9. **Return + remember.** The answer streams back; the turn is saved to the session (Postgres).

Every hop has **error handling**: an upstream failure degrades to a friendly message instead of a
500 (`libs/clients/services.py` maps errors; endpoints wrap the call). *Lesson: in a distributed
system, assume every network call can fail — and make failure graceful.*

---

## Part 6 — Production engineering concepts

### 6.1 Identity & access (Keycloak + RBAC + PEP)
- **Keycloak** is the identity provider (OIDC). Two login models: **public users via SSO →
  Viewer** (read-only), **staff via username/password → Analyst/Administrator**. The realm is
  provisioned **as code** (`infra/keycloak/abc-bank-realm.json`).
- The API **validates** the JWT (signature via JWKS, issuer, roles). Code: `authz/identity.py`.
- **RBAC** (role-based access control): a matrix of which role may use which tool/data
  (`authz/rbac.py`).
- **PEP (Policy Enforcement Point)**: authorization is enforced **in code**, on *every* tool and
  retrieval (`authz/policy.py`) — *not* by asking the LLM nicely. The model cannot bypass it.

### 6.2 State: Redis and Postgres
- **Redis** (in-memory, fast): token-budget counters (atomic `INCRBY`), rate-limit windows, and the
  shared semantic cache. Code: `libs/memory/`.
- **Postgres** (durable, relational): conversation history, ingest jobs, document registry, via
  SQLAlchemy. Code: `libs/db/`. Both have **in-memory fallbacks** so the system runs with zero
  infrastructure for development.

### 6.3 Tools and MCP
Beyond documents, the agent can call **tools**: a **web search**, a **document parser**
(PDF/Word/Excel), and an **MCP** tool. **MCP (Model Context Protocol)** is a standard way for an
agent to call external data/actions; here a real MCP server exposes bank "systems" (employees,
services, incidents) over stdio. Code: `services/ai-tool-service/server.py`,
`libs/orchestrator/mcp_client.py`.

### 6.4 The model gateway (one door for all LLM calls)
Every LLM call goes through `libs/llm/gateway.py` → a provider (`provider_gemini.py`, etc.). This
single choke-point gives us **metering, logging, fallback, and provider-swapping** in one place
(ADR-010). Admins can even change the active model at runtime (write-only API key). *Lesson:
centralize cross-cutting concerns behind one interface.*

### 6.5 Resilience patterns you can name
- **Graceful degradation / fallback** — Gemini → fallback provider → mock; retrieval service →
  in-process index; retired model → self-heal to a known-good model.
- **Timeouts + typed errors** — transport failures become `UpstreamError`/`ToolTimeoutError`.
- **Circuit-breaker-lite** — one retry, then degrade, never hammer.

### 6.6 Observability
- **Structured JSON logs** with correlation ids (`libs/observability/logging.py`) — every event is
  machine-parseable, tied to one request.
- **LLM request/response logging** at the gateway — you can see exactly what was sent/returned.
- **LangSmith tracing** (optional) — visualize the agent's node transitions and spans.

### 6.7 Containerization & orchestration
**Docker Compose** runs all services + Redis + Postgres + Keycloak together, with **healthchecks**
so dependents start only when their dependencies are *ready* (not just started). `docker compose up`
brings up the whole system. Code: `docker-compose.yml`.

---

## Part 7 — How to read the codebase (intern's map)

Start here, in order:
1. `libs/contracts/models.py` — the data types everything passes around (Chunk, Answer, Citation,
   UserContext). Read this first; it's the vocabulary.
2. `libs/rag/` — the retrieval engine (chunking → embeddings → bm25 → hybrid → store).
3. `libs/orchestrator/ops.py` — the agent's steps (classify, retrieve, synthesize, run_tool).
4. `libs/orchestrator/graph_langgraph.py` — how those steps wire into a graph.
5. `libs/llm/` — provider abstraction + gateway.
6. `libs/authz/`, `libs/memory/`, `libs/db/` — security and state.
7. `services/*/app/main.py` — the thin HTTP layer for each service.
8. `tests/` — the clearest, shortest examples of how each piece is *meant* to be used. When unsure
   how something works, read its test.

**How to learn it hands-on:** `make test` (see everything pass), `make demo` (run the pipeline
offline, no keys), then `docker compose up` for the full stack. Trace one question with the logs
open.

---

## Part 8 — Key lessons to take away
1. **Ground the model**: retrieval + citations beat a bare LLM for trust and accuracy.
2. **Hybrid retrieval**: meaning (dense) + text (BM25) + fusion + rerank, then a *few* top chunks.
3. **Separate the brain from the plumbing**: business steps in `libs/`, engines/services around it.
4. **Security in code, not prompts**: the PEP enforces access regardless of what the model does.
5. **Assume failure**: every network/LLM call degrades gracefully.
6. **Centralize cross-cutting concerns**: one gateway for all LLM calls; one logger; one error
   taxonomy.
7. **Offline-first**: deterministic mocks + in-memory stores mean the system (and its tests) run
   with zero credentials, and real backends switch on by env var.
