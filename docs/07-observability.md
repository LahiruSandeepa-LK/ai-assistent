# 07 — Observability

> Covers **Observability (10%)**. LangSmith is **mandatory** (O1). Requirements O1–O6,
> plus structured logging (BE7) and the feedback loop (bonus B5).

## 1. Three pillars

| Pillar | Tool | What it gives the evaluator |
|--------|------|-----------------------------|
| **Tracing** | **LangSmith** | The full agent run tree: every conversation, node transition, tool call, retrieval, LLM call, with inputs/outputs/latency/cost |
| **Logs** | Structured JSON logs | Machine-parseable, correlation-id-linked records across services |
| **Metrics** | `/metrics` (Prometheus format) | Latency, error rate, token/cost, rate-limit hits, retrieval recall proxies |

## 2. LangSmith tracing (O2–O6)

- **Instrumentation:** the agent service sets `LANGSMITH_TRACING=true` and a project per
  environment. LangGraph auto-traces node transitions; tools and the retrieval client are
  wrapped with `@traceable` so tool calls (O3) and retrieval operations (O5) are spans.
- **One run tree per conversation turn** (O2), tagged with `session_id`, `user_id` (hashed),
  `correlation_id`, roles, route, and model used.
- **Agent transitions (O4):** each LangGraph node is a child span, so the Supervisor→Research→
  Validation→Response path is visible with timings and the state diffs.
- **Retrieval spans (O5):** record query, filters, namespaces, candidate counts, fusion and
  rerank scores, and chosen chunks — so retrieval quality is debuggable.
- **Evaluator access (O6):** a dedicated LangSmith project the reviewer can open; the final
  `AgentEvent` returns a **shareable run URL** so a specific answer links straight to its trace
  (used in the demo video, D4).

## 3. The Agent Activity Panel ↔ tracing link (FE4–FE11)

The same `AgentEvent` stream that powers the UI activity panel is the human-facing mirror of
the LangSmith trace: agent state, active LangGraph node, tool calls, retrieval status, memory
updates, validation results, and final generation all appear live, and the trace URL lets the
evaluator drill into any run. Transparency is thus available **both in real time** (panel) and
**post-hoc** (LangSmith).

## 4. Structured logging (BE7)

- JSON logs via `structlog`, one schema across services:
  `{ ts, level, service, correlation_id, session_id, user_id_hash, event, ...fields }`.
- **Correlation id** (`X-Correlation-ID`) is generated at the gateway and propagated through
  every hop and into LangSmith metadata, so a single id ties the UI event, the service logs,
  and the trace together.
- Log levels tuned so an operator can follow a request end-to-end at INFO and debug a node at
  DEBUG without code changes.

## 5. Metrics & alerting

- **RED metrics** per service (Rate, Errors, Duration) + AI-specific: tokens per turn, cost
  per turn, cache hit rate, rerank latency, guardrail-block counts, rate-limit 429s, retry
  counts, recursion depth distribution (watch the butterfly effect).
- Alert thresholds (for a real deployment): error rate, p95 latency, cost per turn, and
  guardrail-block spikes.

## 6. Feedback loop for answer quality (bonus B5)

- The UI shows 👍/👎 + optional comment on each answer. Feedback is written to Postgres and
  pushed to **LangSmith feedback** on the run, building a labeled dataset over time.
- That dataset feeds **offline evaluations** in LangSmith (groundedness, citation accuracy,
  helpfulness via LLM-as-judge) so changes to prompts/retrieval/rerank can be regression-tested
  before shipping. This closes the loop: traces → feedback → dataset → eval → improvement.

## 7. Trade-offs

- **LangSmith is a managed dependency** (data leaves the cluster); for a conservative enterprise, the production
  story would use LangSmith's data controls or a self-hosted collector. For the POC the brief
  mandates LangSmith, so we use it and note the production consideration.
- **Full tracing has overhead/cost**; we sample verbose spans in production but keep 100% for
  the POC/demo so the evaluator sees everything.
