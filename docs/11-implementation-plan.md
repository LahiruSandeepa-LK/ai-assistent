# 11 — Implementation Plan (POC-first)

> The brief says: *cover as much as possible, pick what matters for a POC first, maintain git
> history*. This plan sequences the build so there is a working, demoable system early, then
> depth is layered on. Error handling (E1–E6) and the degradation ladder are specified here.

## 1. Phasing

### Phase 0 — Scaffold (day 0–1)
- Monorepo, `libs/` (contracts, authz stub, observability, llm provider), Docker Compose,
  Makefile, `.env.example`, CI (ruff/mypy/pytest), health endpoints.
- Two Streamlit shells scaffolded: `ui-public` (chat) and `ui-admin` (admin console).
- **Exit:** `docker compose up` brings all containers up healthy; `ui-public` shows an empty
  chat and `ui-admin` shows an (empty) admin console.

### Phase 1 — Retrieval spine (day 1–3) — *RAG 15%*
- Ingestion service + CLI: generate mock corpus (incidents, runbooks, specs, arch docs) → chunk →
  embed → upsert to Pinecone with namespaces + metadata; expose internal `/ingest` API.
- Retrieval service: dense + sparse + RRF + rerank + attribution.
- **Exit:** `/search` returns attributed, reranked chunks; `/ingest` upserts a document; both
  evaluable in isolation.

### Phase 2 — Minimal graph end-to-end (day 3–5) — *LangGraph 15%, Agent 20%*
- LangGraph with Supervisor → Retrieval → Response; shared state + Redis checkpointer.
- Gateway → agent → UI streaming (SSE) with the `AgentEvent` envelope; activity panel v1.
- LangSmith tracing wired (O1–O6).
- **Exit:** ask a question, get a streamed, cited answer, see the trace. **This is the first
  demoable POC.**

### Phase 3 — Research agent / RLM (day 5–7) — *RLM 10%*
- Research subgraph: plan-as-code, decomposition, `Send` fan-out, depth/budget guards,
  aggregation. The outage/payment-failure example working end-to-end.
- **Exit:** a multi-hop question triggers recursion visible in the activity panel + trace.

### Phase 4 — Security, RBAC, rate limiting (day 7–9) — *Security 10%, RBAC 5%*
- Keycloak realm + 3 roles; gateway JWT validation; PEP role checks on tools + retrieval;
  token-bucket rate limiting; prompt-injection + output guardrails; validation node
  (groundedness + citation integrity).
- **Exit:** roles enforced, a Viewer can't use MCP/admin tools even by prompt, injection tests
  pass, 429s are graceful.

### Phase 5 — Admin console, document management, memory, MCP, feedback (day 9–11)
- **Admin Console (`ui-admin`) + `/admin/*` routes** (Administrator-only): document upload /
  update / delete / reindex via the ingestion service, KB browser, feedback + audit review,
  LangSmith trace links; document registry in Postgres.
- Long-term memory (Postgres + vector), summary buffer; MCP server + client; Python analysis
  sandbox; feedback loop → LangSmith datasets; HITL approval node.
- **Exit:** an Administrator uploads a document in the admin console and it becomes searchable in
  the public assistant; a Viewer/Analyst cannot reach `/admin/*`; memory survives turns and
  sessions; MCP tools work and are role-gated; 👍/👎 recorded.

### Phase 6 — Hardening, docs, demo (day 11–12)
- Error-handling matrix + degradation ladder verified; red-team the guardrails; finalize
  README/architecture docs; record the 45-min demo with live LangSmith traces, assumptions &
  trade-offs (D3–D5).

> If time is short, the brief's priorities guide cuts: keep Agent/LangGraph/RAG/RLM/Security/
> Observability (80% of the weight); trim MCP (explicitly lower priority), then long-term
> memory, then HITL — all designed, so they're additive, not blocking.

## 2. Error-handling matrix (E1–E6)

| Failure | Detection | Immediate action | Degraded experience |
|---------|-----------|------------------|---------------------|
| **LLM failure** (E1) | timeout / 5xx / rate limit | retry w/ backoff → **fallback provider** (ADR-003) | if both down: return cached/extractive answer from top chunks + "generation degraded" |
| **Vector DB failure** (E2) | Pinecone error/timeout | retry → serve from **Redis cache** → **sparse-only** | answer from whatever evidence is available; state reduced confidence |
| **MCP failure** (E3) | timeout / connection | **circuit breaker** opens | answer from knowledge base, note the tool was unavailable |
| **Tool timeout** (E4) | `asyncio.wait_for` | cancel, record `AppError`, continue | return partial answer with coverage note |
| **Invalid request** (E5) | Pydantic validation | reject with structured 4xx | UI shows a clear validation message |
| **Sub-agent failure** (butterfly) | per-node try/except | append error, aggregate survivors | "summarized 34/37 sources" honesty |

## 3. Degradation ladder (E6)

```
full answer (hybrid+rerank+LLM+memory+tools)
  └─ rerank down        → RRF-ordered context                (minor quality drop)
      └─ embeddings down → sparse-only retrieval              (lexical only)
          └─ Pinecone down → cache, then "retrieval degraded" (conservative answer)
              └─ MCP down   → knowledge-base-only + note
                  └─ LLM primary down → fallback provider
                      └─ both LLMs down → extractive answer from top chunks + clear notice
```
The app **always returns something truthful**, never a blank 500. Every degradation is traced
and shown in the activity panel so the evaluator sees *why* an answer was limited.

## 4. Testing strategy (Code Quality 5%)

- **Unit:** retrieval fusion/rerank, RBAC policy, token-bucket math, guardrail classifiers,
  RLM plan validation, state reducers.
- **Integration:** gateway→agent→retrieval happy path; degradation paths (kill Pinecone/LLM).
- **Red-team / guardrail tests:** a suite of prompt-injection, exfiltration, tool-abuse, and
  privilege-escalation attempts that must all be refused/contained.
- **Authorization tests:** each role × each tool/namespace, asserting the PEP verdict.
- **Eval:** LangSmith offline eval on a small labeled set (groundedness, citation accuracy).

## 5. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| RLM recursion cost/latency | depth + node budget + model routing + caching |
| Injection via poisoned documents | data/instruction separation + content sanitization + PEP |
| Over-refusal from strict brand guardrails | tune thresholds, log refusals, prefer "safe help" |
| LangSmith/Pinecone/LLM vendor outage | fallbacks + degradation ladder + circuit breakers |
| Scope creep in 12 days | strict phase gates; cut from the low-weight end |

## 6. Demo script (D3–D5)

1. **Public Assistant:** simple lookup → streamed cited answer + open its LangSmith trace.
2. Multi-hop RLM question (outages/payment failures) → show decomposition, recursion, and
   aggregation live in the activity panel and the trace.
3. Role demo: same tool asked as Viewer (denied) vs Analyst (allowed); show a Viewer is refused
   at the Admin Console entirely.
4. **Admin Console:** upload/update a document → watch it index → ask the Public Assistant a
   question only answerable from the new document → grounded, cited answer.
5. Injection attempt → guardrail refusal.
6. Kill Pinecone → watch graceful degradation.
7. Narrate assumptions & trade-offs throughout (D5).
