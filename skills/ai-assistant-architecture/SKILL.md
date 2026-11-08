---
name: ai-assistant-architecture
description: Design, build, or review the ABC Bank AI Assistant — an agentic RAG platform (LangGraph multi-agent, RLM, hybrid retrieval on Pinecone, memory, MCP tools, LangSmith observability, security/guardrails/RBAC/rate-limiting) with two interfaces (public chat + admin console) as a Docker-Compose microservice monorepo. Use when adding a service, changing the architecture, writing an ADR, or checking a change against the design.
---

# Enterprise AI Assistant — Architecture Skill

Authoritative design lives in `docs/` (01 architecture, 02 C4, 03 agents, 04 RAG, 05 memory,
06 security, 07 observability, 08 stack, 09 API, 10 deployment, 11 plan, 12 validation) and
`docs/adr/`. Diagrams in `diagrams/*.drawio`. Read `docs/00-requirements-traceability.md`
first — it maps every requirement to where it lives.

## Persona
The assistant is branded **ABC Bank** — a *fictional* example company used only for a consistent
brand voice. Use **no real organization and no sensitive/regulated/real customer data**; all
documents are mock. Keep the brand-safety guardrail, but never introduce real or sensitive data.

## Non-negotiable invariants (do not regress these)

0. **Two separate interfaces (ADR-009).** `ui-public` (chat, all roles) and `ui-admin` (document
   management + ops, **Administrators only**) are distinct containers over distinct gateway route
   groups (`/api/*` vs `/admin/*`). Never add admin/document-management capability to the public
   app, and never expose `/admin/*` or `/ingest` to non-Administrators. Uploaded documents are
   validated + sanitized at ingestion before they enter the corpus.
1. **Authorization is enforced in code, never by the prompt.** Roles come from the
   gateway-signed context (Keycloak JWT), checked at the Policy Enforcement Point before every
   tool call and retrieval, plus an `access_level` retrieval filter. The agent cannot bypass it.
2. **Retrieval is hybrid + attributed.** Dense + sparse → RRF fusion → cross-encoder rerank →
   top-k section chunks with `{doc_id,title,section,url,scores}`. Every citation must resolve to
   a retrieved `doc_id` (hallucinated-citation guardrail).
3. **RLM, not context-stuffing.** The Research agent explores via metadata, emits a
   schema-validated plan-as-code (never `eval`), decomposes, retrieves targeted sections, fans
   out sub-agents with `Send` under `MAX_DEPTH` + `NODE_BUDGET`, and aggregates.
4. **Everything is traced.** One LangSmith run tree per turn; nodes/tools/retrieval are spans;
   the same `AgentEvent` stream powers the UI activity panel and carries the trace URL.
5. **It degrades, never crashes.** Follow the degradation ladder (`docs/11`): rerank→RRF,
   embeddings→sparse, Pinecone→cache→sparse, MCP→circuit-break, LLM→fallback→extractive.
   Return something truthful and say what was limited.
6. **Async all the way.** `async def` handlers, async clients, `asyncio.gather` for parallel
   retrieval, `wait_for` timeouts, retries with backoff + circuit breakers.
7. **One monorepo, independent containers.** Shared code only via `libs/` (contracts, authz,
   observability, llm); services talk over HTTP, never import each other.

## When adding or changing a service
- Put shared types/behavior in `libs/`, not in the service.
- Add a Dockerfile + healthcheck + `depends_on: service_healthy` + `.env` keys (update
  `.env.example`).
- Emit `AgentEvent`s and LangSmith spans for any user-visible step.
- Add unit + integration + (if it touches auth/tools/retrieval) red-team/authz tests.
- If the change is a real decision with alternatives, write an ADR (`engineering:architecture`
  format) in `docs/adr/`.

## When reviewing a change
Run it against the 7 invariants above and the traceability matrix. A change that weakens
authorization, removes attribution, unbounds recursion, drops tracing, or turns a graceful
degrade into a hard failure is a blocker. Prefer the `architect-evaluator-loop` skill for a
structured review.

## Tech stack (see `docs/08` + ADRs)
Streamlit · FastAPI(async) · LangGraph · Claude (primary)/OpenAI (fallback) behind
`libs/llm.LLMProvider` · Pinecone (sparse-dense, namespaces, metadata) · cross-encoder rerank ·
Redis (checkpointer/cache/rate-buckets) · Postgres (long-term memory/feedback/audit) ·
Keycloak (OIDC/RBAC) · MCP SDK · LangSmith · Docker Compose.
