# 08 — Technology Stack

> The "what" and "why" of every technology. Decisions with meaningful alternatives have a
> dedicated ADR (see `docs/adr/`).

## 1. Stack at a glance

| Layer | Choice | Why (short) | ADR |
|-------|--------|-------------|-----|
| UI (×2) | **Streamlit** | Mandated; two apps — `ui-public` (chat + transparency) and `ui-admin` (doc mgmt/ops, Admin-only) | ADR-009 |
| API | **FastAPI (async)** | Mandated; first-class async, Pydantic, SSE | — |
| Language | **Python 3.11+** | Mandated; AI ecosystem | — |
| Orchestration | **LangGraph** | Mandated; explicit state machine, checkpointer, interrupt, Send | ADR-001 |
| LLM (primary) | **Anthropic Claude** | Strong tool-use + reasoning + injection robustness | ADR-003 |
| LLM (fallback) | **OpenAI** | Availability/resilience behind one interface | ADR-003 |
| Embeddings | **Managed embedding model** | Quality + no GPU to run | ADR-003 |
| Vector DB | **Pinecone** | Mandated; native sparse-dense hybrid, namespaces, metadata | ADR-002 / ADR-004 |
| Reranker | **Cross-encoder reranker** (hosted or `sentence-transformers`) | Precision uplift | ADR-004 |
| Tracing | **LangSmith** | Mandated | ADR-001 |
| Auth | **Keycloak (OIDC)** | Real RBAC; "no authz bypass" is graded | ADR-005 |
| Short-term memory / cache / rate limit | **Redis** | Fast, atomic ops, checkpointer backend | ADR-006 / ADR-008 |
| Durable store (long-term memory, feedback, audit) | **Postgres** | Relational durability | ADR-006 |
| MCP | **MCP Python SDK** | Mandated tool interface for enterprise data | — |
| Packaging | **Docker + Docker Compose** | Mandated; multi-service local deploy | — |
| Sandbox (Python Analysis tool) | **Restricted subprocess / RestrictedPython / container** | Safe structured analysis | — |
| Tooling | **ruff, mypy, pytest, pre-commit** | Code quality (graded 5%) | — |
| Logging | **structlog** | Structured JSON logs | — |

## 2. Libraries (indicative)

- `langgraph`, `langchain-core`, `langsmith`
- `langchain-anthropic`, `langchain-openai` (behind `libs/llm.LLMProvider`)
- `pinecone-client`
- `fastapi`, `uvicorn`, `sse-starlette`, `httpx` (async clients), `pydantic`, `pydantic-settings`
- `streamlit`
- `redis`, `sqlalchemy`/`asyncpg`, `alembic`
- `python-jose`/`authlib` (JWT/OIDC), `rank-bm25` or Pinecone sparse encoders
- `mcp` (Model Context Protocol SDK)
- `structlog`, `prometheus-client`
- Dev: `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `pre-commit`

## 3. Model selection rationale (L2 — expanded in ADR-003)

- **Why Claude primary:** strong multi-step reasoning and tool-use (needed for the Supervisor
  and RLM), good instruction-following under adversarial input (helps injection defense), and
  reliable structured output (plan-as-code, JSON verdicts).
- **Why a fallback:** the error-handling requirement (E1) demands we survive an LLM outage;
  an OpenAI fallback behind `LLMProvider` gives resilience without code changes.
- **Why model routing:** cheap/fast model for classification & decomposition, strong model for
  synthesis & validation — controls latency and cost (the dominant run-cost of an agentic
  system).
- **Why managed embeddings:** avoids running/scaling a GPU embedding service for the POC;
  swappable via config.

## 4. Why not alternatives (summary)

- **Plain LangChain / custom orchestration** → no first-class state machine, checkpointing,
  interrupt, or fan-out; LangGraph is also what the brief asks for. (ADR-001)
- **Weaviate/Qdrant/pgvector instead of Pinecone** → Pinecone is mandated; also gives managed
  hybrid without ops. (ADR-002)
- **Self-hosted LLM** → ops/GPU cost and weaker tool-use for a POC; kept as a future option
  behind the provider interface. (ADR-003)
- **Polyrepo** → versioning tax for a small team; monorepo keeps contracts atomic. (ADR-007)
