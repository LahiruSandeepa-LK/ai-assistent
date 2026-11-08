# 02 — C4 Model

The architecture is documented with the **C4 model** (Context → Container → Component). The
editable diagrams are in `/diagrams/*.drawio` (open at [app.diagrams.net](https://app.diagrams.net)).
This document is the narrative companion so the diagrams are readable without a tool.

| Level | File | What it shows |
|-------|------|---------------|
| L1 Context | `diagrams/c4-l1-context.drawio` | The system as one box, its users and external systems |
| L2 Container | `diagrams/c4-l2-container.drawio` | The 10 containers (two UIs) and how they talk |
| L3 Component | `diagrams/c4-l3-component-agent.drawio` | Inside the Agent service: graph nodes, tools, guardrails, memory |
| Supplementary | `diagrams/langgraph-agent-flow.drawio` | The LangGraph state machine (nodes + conditional edges) |
| Supplementary | `diagrams/rag-hybrid-retrieval-sequence.drawio` | Hybrid retrieval + rerank sequence |
| Supplementary | `diagrams/deployment-docker-compose.drawio` | Deployment / Compose topology |
| Supplementary | `diagrams/security-rbac-flow.drawio` | AuthN/AuthZ + RBAC + rate-limit flow |
| Supplementary | `diagrams/admin-document-management-flow.drawio` | Admin Console → document upload → ingestion → Pinecone |

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

The ten containers from `01-system-architecture.md §2` (note the **two UI containers**). Key
relationships drawn:

- **ui-public** → Gateway: `HTTPS` (chat request, bearer token); Gateway → ui-public: `SSE`
  (tokens + events).
- **ui-admin** → Gateway: `HTTPS` to the **admin routes** (document management, feedback,
  audit) — Administrator-only.
- Gateway ↔ Keycloak: OIDC token validation (JWKS).
- Gateway → Agent: internal REST with signed user context (chat path).
- Gateway → Ingestion: internal REST to `/ingest` (admin document-management path).
- Agent → Retrieval: hybrid search REST.
- Agent → MCP: MCP protocol (tool calls).
- Agent ↔ Redis: checkpointer (short-term memory) + rate-limit read.
- Agent ↔ Postgres: long-term memory, feedback, audit.
- Ingestion ↔ Postgres: document registry (status).
- Retrieval → Pinecone: upsert/query.
- Retrieval → Embedding Provider: embed query.
- Agent → LLM Provider: completions/tool-use.
- All services → LangSmith: traces.
- Ingestion → Pinecone: upsert (namespaces + metadata) — both batch CLI and admin-triggered.

**Trust boundaries** (drawn as dashed containers):
1. *Public edge*: ui-public + Gateway.
2. *Admin edge*: ui-admin + Gateway admin routes (Administrator-only).
3. *Internal mesh*: Agent, Retrieval, Ingestion, MCP, Redis, Postgres, Keycloak.
4. *Managed cloud*: Pinecone, LLM, Embedding, LangSmith.

## L3 — Component (Agent service)

Inside `agent`:

- **Graph Builder** — assembles the LangGraph `StateGraph` with checkpointer.
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
- **Memory managers** — short-term (checkpointer) + long-term (vector/Postgres).
- **Policy Enforcement Point (PEP)** — consults `libs/authz` before every tool call.
- **Trace emitter** — wraps nodes/tools with LangSmith spans and emits `AgentEvent`s.

See `03-agent-architecture.md` for behavior and `diagrams/c4-l3-component-agent.drawio` for
the picture.
