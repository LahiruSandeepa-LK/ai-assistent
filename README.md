# Enterprise AI Assistant — ABC Bank (fictional)

> **AI Lead Technical Assessment** · Author: Lahiru · Role: AI Solution Architect / AI-ML Lead
> Status: **Design complete + runnable POC implemented** (offline-capable; real Pinecone/LLM/Keycloak via env).

An agentic RAG assistant over organizational knowledge, branded as **ABC Bank** (a *fictional*
example company — no real or sensitive data). Microservice **monorepo** on **Docker Compose**,
orchestrated with LangGraph, with a **Recursive Language Model (RLM)** research flow, hybrid
retrieval, two interfaces (public chat + admin console), per-user **token budgets**, guardrails,
RBAC, and full observability.

The core engine runs **offline with zero external credentials** (deterministic mock LLM + local
hybrid index), and swaps in real **Pinecone / Anthropic / OpenAI / Keycloak / Redis / Postgres**
when the matching env vars are set.

## Quick start

```bash
make install          # dev deps (the engine itself is stdlib-only)
make test             # unit + e2e + tools + backends + auth/admin/llm (58 tests)
make demo             # full pipeline over the sample corpus, offline
make eval             # accuracy golden-set scorecard (Recall@k, citation integrity)
make api              # run the API gateway at :8000 (dev auth: Bearer viewer|analyst|admin)
make up               # full containerised stack (docker compose)
```

Example (what `make demo` shows): asking *"root cause of the 2026-01-21 payment outage?"* →
`Ledger PostgreSQL connection pool exhaustion. [INC-2026-0121] [INC-2025-1219]` — grounded, cited,
with the router/retrieval/validation events streamed live, token usage metered, and a repeat of
the same question served from the **semantic cache**.

## Project structure (matches the code)

```
AI_Assistant/
├── README.md  Makefile  docker-compose.yml  docker-compose.dev.yml
├── .env.example  pyproject.toml  conftest.py  pytest.ini  requirements-dev.txt
│
├── libs/                              # the ENGINE (pure-stdlib core; shared by every service)
│   ├── contracts/     models.py · errors.py          # dataclasses, AgentEvent, error taxonomy
│   ├── authz/         rbac.py · policy.py · identity.py   # role matrix, PEP, dev/Keycloak auth
│   ├── authclient/    keycloak_client.py             # UI-side token acquisition (SSO + password)
│   ├── observability/ logging.py                      # structured JSON logs + correlation ids
│   ├── llm/           provider.py · gateway.py · config_store.py   # providers + metering + runtime LLM config
│   ├── rag/           chunking · embeddings · bm25 · vectorstore(+pinecone) · hybrid · store · ingest
│   ├── memory/        conversation.py · usage.py      # history, summary, cache, token budget
│   ├── admin/         jobs.py · ingest_runner.py      # upload job store + staged indexing w/ progress
│   └── orchestrator/  graph.py(+graph_langgraph) · ops · prompts · guardrails · tools
│                       · mcp_client · mcp_data · tool_web · tool_docparser   # the brain + tools
│
├── services/                         # thin deployables that import libs
│   ├── ai-assistant-api/   app/main.py        # chat edge: auth·RBAC·rate-limit·TOKEN gate·SSE
│   ├── ai-orchestrator/    app/main.py        # /agent/run (LangGraph brain)
│   ├── ai-knowledge-service/
│   │   ├── retrieval/      app/main.py        # /search  (READ path)
│   │   └── ingestion/      app/main.py · cli.py · sample_docs/   # /ingest (WRITE) + 20-doc corpus
│   ├── ai-tool-service/    app/main.py · server.py   # REST /call + REAL MCP server (FastMCP/MCPServer, stdio)
│   ├── ai-conversation-service/ app/main.py   # /context · /usage/check · /usage/record
│   ├── ai-model-gateway/   app/main.py        # /complete (routing + fallback + metering)
│   ├── ai-admin-service/   app/main.py · eval/run_eval.py   # doc upload+progress, LLM config, eval (admin-only)
│   ├── ui-public/          app.py             # Streamlit chat + SSO/staff login + activity panel
│   └── ui-admin/           app.py             # Streamlit admin console (login, upload+progress, LLM config)
│
├── infra/keycloak/abc-bank-realm.json   # realm-as-code: clients, roles, SSO broker, seeded staff
├── scripts/demo.py                   # end-to-end offline demo
├── tests/                            # unit · e2e · langgraph · tools · backends · authclient · admin · llm-config (58 tests)
├── fixtures/sample_docs/ + golden.jsonl   # small corpus + golden set for tests/eval
│
├── docs/   00–15 design docs + adr/ADR-001…010   (architecture, RAG, security, token budget, eval)
├── diagrams/  12 .drawio (C4, service map, flows, RAG ingest, eval)
└── skills/    3 reusable SKILL.md
```

> **Service ↔ engine:** business logic lives in `libs/` so it is shared, unit-tested, and
> runnable standalone; each `services/*` is a thin FastAPI/Streamlit entrypoint. The
> `ai-assistant-api` runs the orchestrator in-process for the POC (set `ORCHESTRATOR_URL` to call
> it over HTTP instead). `docs/13-service-topology.md` is the canonical service map.

## What is real vs. mocked (honest status)

| Area | Status |
|------|--------|
| Section-aware chunking, BM25 + local dense + **RRF fusion + rerank**, metadata/access filter | ✅ real, tested |
| **Orchestration** — real **LangGraph** `StateGraph` (checkpointer, conditional edges, **`Send`** fan-out for RLM, **`interrupt`** HITL); dependency-free fallback pipeline when `langgraph` is absent (`USE_LANGGRAPH=off`) | ✅ real, tested |
| RLM research (decompose → `Send` fan-out → aggregate), router (cache / context / retrieval / research) | ✅ real, tested |
| **Observability** — **LangSmith** tracing of node transitions + LLM/retriever spans (auto when enabled), structured JSON logs, live activity-event stream | ✅ wired (no-op offline) |
| Guardrails (prompt-injection screen, **citation integrity**, secret redaction), RBAC + PEP | ✅ real, tested |
| **Tools + agent tool-routing** — knowledge_search, **MCP** (real FastMCP/MCPServer over stdio; in-process fallback), **web_search** (Tavily when `TAVILY_API_KEY` set; offline stub otherwise), **document_parser** (md/html/txt stdlib; pdf/docx optional), python_analysis — router detects tool-intent, PEP-gated, traced | ✅ real, tested |
| **Token budget** (pre-check + post-call metering), rate limiting, memory + summarize-after-10 + semantic cache | ✅ real, tested |
| LLM | **MockProvider** (deterministic, extractive, cited) offline; **Gemini / Anthropic / OpenAI** adapters hook in via `LLM_PROVIDER` + key (see "Connecting a real LLM") |
| Vector DB | **in-memory** cosine index offline; **real Pinecone adapter** (`vectorstore_pinecone.py`, lazy index creation + namespaces, same interface) activates via `PINECONE_API_KEY` |
| Auth | **dev users** (viewer/analyst/admin) offline; **real Keycloak OIDC** (`AUTH_MODE=keycloak`) — realm-as-code, **SSO identity brokering → Viewer** for public users, **username/password** for staff (admin/analyst), JWKS-verified JWT, realm + client role mapping |
| Admin console | **document upload** (pdf/docx/xlsx/md/txt/html) with **live indexing progress**, and **runtime LLM configuration** (create-only; API keys write-only, never shown or returned) — Administrator-only |
| Redis / Postgres | optional; in-memory fallbacks offline |

## Connecting a real LLM (e.g. Gemini)

Every model call funnels through `ai-model-gateway` → `libs/llm` (ADR-010), so switching from
the offline mock to a real model is **config only** — no code change:

```bash
# Google Gemini
export LLM_PROVIDER=gemini
export GEMINI_API_KEY=...                 # from Google AI Studio
export GEMINI_MODEL_STRONG=gemini-2.5-pro   # synthesis/validation (set to a model you have)
export GEMINI_MODEL_FAST=gemini-2.5-flash   # routing/summarise (cheaper)
pip install google-genai
# optional resilience: fall back to another provider on error (ADR-003 / E1)
export LLM_FALLBACK=openai   OPENAI_API_KEY=...
```

Then `make demo` / `make api` use Gemini for synthesis and summarisation, and **real token
usage** (`usage_metadata`) is metered against each user's budget automatically.

`LLM_PROVIDER` accepts `gemini | anthropic | openai | mock`. Each adapter
(`libs/llm/provider_gemini.py`, `provider_anthropic.py`, `provider_openai.py`) implements one
method — `complete(system, user, model) -> Completion` — and maps the provider's response text +
token counts into the pipeline. To add any other model, drop in a new `provider_*.py` with that
one method and register it in `get_provider()`. Model slugs are env-overridable because they
change often; set them to models your key can access.

## Connecting a real vector DB (Pinecone)

The whole RAG engine reads/writes the vector store through one interface
(`libs/rag/vectorstore.py`), so switching from the in-memory index to Pinecone is **config
only** — `get_vector_store()` returns the Pinecone adapter the moment a key is present:

```bash
export PINECONE_API_KEY=...
export PINECONE_INDEX=ai-assistant        # default
export PINECONE_NAMESPACE=abc-bank        # optional, for multi-tenant isolation
export PINECONE_CLOUD=aws                  # serverless spec (default aws / us-east-1)
export PINECONE_REGION=us-east-1
pip install pinecone
```

The adapter (`libs/rag/vectorstore_pinecone.py`) creates the index lazily on first upsert
using the live embedding dimension — so it works with the offline 256-dim hashing embedder
**or** a 1536-dim OpenAI embedder with no extra config — and deletes by `doc_id` reliably
(id tracking, with a metadata-filter fallback for pod indexes). Pair it with
`EMBEDDING_PROVIDER=openai` for production-grade recall.

## Authentication — two login models (Keycloak)

The `abc-bank` realm is provisioned **as code** (`infra/keycloak/abc-bank-realm.json`) and
auto-imported on `docker compose up`. Two distinct login paths, by design:

- **Public users → SSO (identity brokering) → Viewer.** The public chat UI's *"Continue with
  SSO"* sends the user straight to the corporate IdP through Keycloak (`kc_idp_hint`), using
  Authorization-Code + PKCE. A first-login identity-provider mapper grants the **Viewer** role,
  so external users get read-only access and nothing more. (Activate the broker by setting the
  `SSO_*` client creds; without them, staff sign-in still works for the demo.)
- **Staff (admin / analyst) → username / password.** Both UIs offer a credential form that uses
  the OIDC Resource-Owner Password grant against the `ai-assistant-admin` client. Seeded demo
  users: `admin / Admin#12345` (Administrator), `analyst / Analyst#12345` (Analyst).

```bash
export AUTH_MODE=keycloak
export KEYCLOAK_URL=http://host.docker.internal:8080   # stable issuer for browser + containers
export KEYCLOAK_REALM=abc-bank
export KEYCLOAK_WEB_CLIENT_ID=ai-assistant-web          # public SSO client (auth-code + PKCE)
export KEYCLOAK_ADMIN_CLIENT_ID=ai-assistant-admin      # staff client (password grant)
export KEYCLOAK_SSO_IDP=corporate-sso                   # brokered IdP alias
export KEYCLOAK_VERIFY_AUD=false
# optional: map your IdP's role names onto the app's three roles
export KEYCLOAK_ROLE_MAP="kc-reader:Viewer,kc-analyst:Analyst,kc-admin:Administrator"
```

The API side only **validates** tokens: it checks each bearer JWT against the realm JWKS
(cached, rotation-safe), verifies the issuer, and maps **realm + client roles** onto
Viewer/Analyst/Administrator — the same roles the PEP and RBAC matrix enforce. The UIs
**acquire** tokens via `libs/authclient`. Dev mode (`AUTH_MODE=dev`) still works offline with
the viewer/analyst/admin shortcuts. **Networking note:** both the browser (SSO redirect) and the
containers (token/JWKS calls) use `http://host.docker.internal:8080`, and Keycloak pins that as
its issuer (`KC_HOSTNAME_URL`), so the issuer is identical on both sides — the one thing to
verify live on `docker compose up`. On a **Linux** host (not Docker Desktop) the browser also
needs a hosts entry — `127.0.0.1 host.docker.internal` in `/etc/hosts` — for the SSO redirect;
staff password login is server-side and unaffected. The brokered `corporate-sso` IdP ships with
`REPLACE_WITH_*` placeholders in the realm file — set real IdP client creds there (or in the
Keycloak admin console) to activate public SSO; staff sign-in works without it.

## Admin console

Administrator-only (`services/ui-admin`, `ai-admin-service`):

- **Document upload + live indexing progress.** Upload a PDF, Word, Excel, Markdown, HTML or
  text file; it's parsed, chunked and indexed in a background job, and the UI shows a progress
  bar advancing through *extracting → chunking → indexing → done* (polling `/admin/jobs/{id}`).
  Offline, the admin service and the chat API share the index through a file snapshot
  (`INDEX_PATH` on the `kbindex` volume), so a freshly uploaded document is immediately
  searchable in chat; with Pinecone configured, that shared store is used instead.
- **Runtime LLM configuration.** Create an LLM config (provider + model slugs + API key) and
  activate it live — the model gateway rebuilds to use it. **Create-only** (no edit after
  creation) and the **API key is write-only**: it's accepted once, stored server-side, and
  **never returned by any endpoint or shown in the UI** (list/response carry only a
  `has_secret` flag). Secrets live in a gitignored server-only file for the POC; back it with a
  secrets manager (Vault/KMS) in production — see `docs/adr/ADR-011`.

## Enabling LangSmith tracing

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=...
export LANGSMITH_PROJECT=ai-assistant
```
With these set, the LangGraph node transitions auto-trace to LangSmith, the LLM and retriever
calls appear as spans, and each answer carries a shareable `trace` event with the run URL (for the
demo video, deliverable D4). Unset, everything runs identically with tracing off.

## Validation (architect ⇄ evaluator loop)

`make test` → **58 passing** (1 env-dependent skip). `make eval` on the golden set → **Recall@k = 1.0, citation
integrity = 1.0**. The loop caught and fixed a real retrieval-precision bug (date/ID queries
ranked the wrong incident until document metadata was indexed with each chunk).

## Reading the design
Start with `docs/00-requirements-traceability.md` and `docs/13-service-topology.md`; the full
index is in that folder (00–15 + ADRs 001–010) with diagrams in `diagrams/`.
