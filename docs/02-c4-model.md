# 02 — C4 Model

The architecture is documented with the **C4 model** (Context → Container → Component). The
editable diagrams are in `/diagrams/*.drawio` (open at [app.diagrams.net](https://app.diagrams.net)).
This document is the narrative companion so the diagrams are readable without a tool.

| Level | File | What it shows |
|-------|------|---------------|
| L1 Context | `diagrams/c4-l1-context.drawio` | The system as one box, its users and external systems |
| L2 Container | `diagrams/c4-l2-container.drawio` | The `ai-*` services (incl. conversation-service + model-gateway) and how they talk |
| L3 Component | `diagrams/c4-l3-component-agent.drawio` | Inside **ai-orchestrator**: router + graph nodes, tools, guardrails, memory |
| Supplementary | `diagrams/service-connection-map.drawio` | Service wiring with protocols (docs/13) |
| Supplementary | `diagrams/langgraph-agent-flow.drawio` | The LangGraph state machine (router-first + conditional edges) |
| Supplementary | `diagrams/request-flow-token-budget.drawio` | End-to-end flow: token gate + cache/context skip (docs/14) |
| Supplementary | `diagrams/rag-hybrid-retrieval-sequence.drawio` | Hybrid retrieval + rerank sequence (read path) |
| Supplementary | `diagrams/rag-ingestion-pipeline.drawio` | Ingestion write path: chunk → embed → upsert (docs/04, docs/13) |
| Supplementary | `diagrams/deployment-docker-compose.drawio` | Deployment / Compose topology |
| Supplementary | `diagrams/security-rbac-flow.drawio` | AuthN/AuthZ + RBAC + rate-limit + token-budget flow |
| Supplementary | `diagrams/admin-document-management-flow.drawio` | Admin Console → ingestion → Pinecone |
| Supplementary | `diagrams/evaluation-pipeline.drawio` | Accuracy/eval harness loop (docs/15) |

---

## L1 — System Context

**People** (and which interface they use)
- **Viewer** (e.g., employee): **Public Assistant** — chat + search only.
- **Analyst**: **Public Assistant** — search + analytics + MCP tools.
- **Administrator**: **Public Assistant** (all tools) **and** the **Admin Console** (document
  management, feedback/audit review, observability).
- **Evaluator** (reviewer): observes internal behavior via the activity panel + LangSmith.

**Software system**
- **ABC Bank AI Assistant** (ABC Bank = fictional example company) — answers questions over
  internal knowledge with grounded, explainable, access-controlled responses. Exposes **two
  interfaces**: Public Assistant (chat) and Admin Console (operations).

**External systems**
- **Pinecone** — managed vector database (dense + sparse).
- **LLM Provider** — Anthropic Claude (primary), OpenAI (fallback).
- **Embedding Provider** — text embedding model.
- **LangSmith** — tracing & evaluation.
- **Keycloak** — identity provider (can be treated as internal infra but shown as a trust boundary).

Relationships: users chat with the system; the system calls Pinecone for retrieval, the LLM
for reasoning/generation, the embedding provider for vectors, Keycloak for identity, and
streams every step to LangSmith.

## L2 — Containers

The `ai-*` services from `01-system-architecture.md §2` / `docs/13` (full matrix there). Key
relationships drawn:

- **ui-public** → **ai-assistant-api**: `HTTPS` chat; api → ui-public: `SSE` (tokens + events).
- **ui-admin** → **ai-admin-service**: `HTTPS` admin ops (Administrator-only).
- ai-assistant-api ↔ Keycloak: OIDC validation (JWKS).
- ai-assistant-api → ai-conversation-service: **token-budget pre-check** + user state.
- ai-assistant-api ↔ Redis: rate-limit buckets.
- ai-assistant-api → ai-orchestrator: internal REST (signed user context) + SSE.
- ai-orchestrator → ai-conversation-service: load context (summary+turns+profile) + **cache hit?**; write turns.
- ai-orchestrator → ai-knowledge-service (retrieval): hybrid search.
- ai-orchestrator → ai-tool-service: MCP / tool calls.
- ai-orchestrator → **ai-model-gateway**: all LLM calls.
- ai-model-gateway → LLM Provider: completions/tool-use; → ai-conversation-service: **token metering**.
- ai-conversation-service ↔ Redis/Postgres: short-term+cache+usage / long-term+ledger.
- ai-knowledge-service → Pinecone + Embedding Provider: query/upsert, embed.
- ai-admin-service → ai-knowledge-service (ingest): document ops; → Postgres/LangSmith: analytics/eval.
- All services → LangSmith: traces; correlation+session id on every hop (OpenTelemetry for hops).

**Trust boundaries** (drawn as dashed containers):
1. *Public edge*: ui-public + ai-assistant-api.
2. *Admin edge*: ui-admin + ai-admin-service (Administrator-only).
3. *Internal mesh*: ai-orchestrator, ai-knowledge-service, ai-tool-service, ai-conversation-service, ai-model-gateway, Redis, Postgres, Keycloak.
4. *Managed cloud*: Pinecone, LLM, Embedding, LangSmith.

## L3 — Component (ai-orchestrator)

Inside `ai-orchestrator`:

- **Graph Builder** — assembles the LangGraph `StateGraph` with checkpointer.
- **Router node (first)** — token-aware entry: cache hit? answerable-from-context? else classify & route.
- **Supervisor node** — intent classification, task decomposition, routing.
- **Retrieval agent node** — single-shot hybrid search for direct questions.
- **Research agent node (RLM)** — plan-as-code, decompose, recursive `Send` fan-out,
  aggregate; the recursion engine.
- **Validation node** — groundedness/citation check, guardrail verdicts, retry decision.
- **Response node** — final answer synthesis + streaming.
- **HITL approval node** — interrupt for high-risk tool actions (bonus).
- **Tool registry** — Knowledge Search, MCP client, Python Analysis (sandboxed).
- **Guardrail components** — input (prompt injection), content (retrieved-data sanitization),
  output (brand + hallucinated-citation + invalid-response).
- **Memory client** — reads/writes context via **ai-conversation-service** (short-term checkpointer,
  long-term memory, semantic cache); does not own the stores itself.
- **LLM client** — all model calls go through **ai-model-gateway** (routing, fallback, token metering).
- **Policy Enforcement Point (PEP)** — consults `libs/authz` before every tool call.
- **Trace emitter** — wraps nodes/tools with LangSmith spans and emits `AgentEvent`s.

See `03-agent-architecture.md` for behavior and `diagrams/c4-l3-component-agent.drawio` for
the picture.
