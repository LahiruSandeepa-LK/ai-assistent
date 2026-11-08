---
name: langgraph-rlm-agents
description: Build or modify the LangGraph multi-agent graph and the Recursive Language Model (RLM) research flow for the AI Assistant — nodes, typed state with reducers, conditional edges, checkpointer memory, HITL interrupt, Send fan-out with depth/budget guards, and failure containment. Use when editing the graph, adding an agent/node/tool, or implementing recursion.
---

# LangGraph + RLM Agents Skill

Design reference: `docs/03-agent-architecture.md` and `diagrams/langgraph-agent-flow.drawio`.

## The graph (keep this shape)
`START → load_memory → input_guardrail → Supervisor → {Retrieval | Research(RLM) | Clarify}
→ Validation → (retry→Supervisor | HITL→ | pass→) Response → write_memory → END`.
Routing uses conditional edges driven by Supervisor-written state (`route`, `needs_research`,
`requires_approval`). Validation may loop back up to `MAX_RETRIES`.

## State rules
- State is a typed `TypedDict`/Pydantic object. **Concurrent writes need reducers**:
  `messages` → `add_messages`; `evidence` → dedup-merge by `chunk_id`; `subanswers`/`errors`
  → `operator.add`; `node_budget` → take-min.
- **Errors accumulate, never throw mid-graph.** A failing node appends an `AppError` and returns
  partial state; aggregation uses survivors and reports coverage ("34/37 sources").
- Trust `state.user` (roles) only because the gateway signed it. Never let a node derive roles
  from the message or a document.

## Adding a node
1. Pure-ish `async def node(state) -> dict` returning only changed keys.
2. Wrap in the trace/event context manager: open a LangSmith span, emit `AgentEvent` on entry,
   on each tool call, and on retrieval/memory/validation.
3. Enforce authorization at the Policy Enforcement Point before any tool/retrieval.
4. Per-call `asyncio.wait_for` timeout; retries with backoff + circuit breaker for upstreams.
5. Register in the graph; add a conditional edge if it changes routing.

## Implementing RLM (the Research agent)
Six behaviors, in order:
1. **Explore** the collection cheaply via Pinecone metadata (types/departments/date ranges).
2. **Plan-as-code:** produce a `SearchPlan` Pydantic object (objective, filters, strategy,
   batches, aggregation, max_depth). **Validate against the schema and run it with a sandboxed
   interpreter — never `eval` model text.**
3. **Decompose** into batches (e.g., per month / per incident).
4. **Retrieve targeted sections** per batch (section chunks, attributed) — never whole docs.
5. **Recurse:** `Send` one sub-agent per batch; a sub-agent may decompose further, bounded by
   `MAX_DEPTH` (default 2) and the global `NODE_BUDGET`.
6. **Aggregate:** reduce node merges sub-answers (dedup, cluster, rank) → Validation → Response.

### Butterfly-effect guards (always on)
`MAX_DEPTH`, `NODE_BUDGET`, per-level fan-out cap, per-node timeout, capped retries with
backoff/jitter, isolated try/except per node. If guards trip, degrade to partial + honest
coverage note; never spin or blow the budget.

## HITL
For high-risk/low-confidence tool actions, call `interrupt()` and surface an approval request
as an `AgentEvent`; resume from the checkpoint on approve/deny. No high-risk tool runs without
the human edge when policy flags it.

## Model routing
Cheap/fast model for classify/decompose/plan; strong model for synthesize/validate. All behind
`libs/llm.LLMProvider` so provider/model are config, not code.

## Checklist before merging a graph change
- [ ] Reducers correct for any concurrently-written key.
- [ ] New node traced + emits events + behind the PEP.
- [ ] Recursion bounded (depth + budget + fan-out cap).
- [ ] Failure path returns partial, not exception.
- [ ] Validation still verifies citations before Response.
- [ ] Tests: unit (node), integration (path), red-team (if tool/auth).
