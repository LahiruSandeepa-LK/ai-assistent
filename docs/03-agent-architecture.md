# 03 — Agent Architecture (LangGraph + RLM)

> Covers evaluation areas **Agent Architecture (20%)**, **LangGraph Usage (15%)**,
> **RLM Implementation (10%)**, and bonus **multi-agent collaboration / HITL**.

## 1. Design goal

Build a **multi-agent system where specialization, not a single monster prompt, drives
quality** — and where the agent *reasons over* a large document collection using a
**Recursive Language Model (RLM)** pattern instead of stuffing documents into one context
window. Every transition must be observable and every decision explainable.

LangGraph is the orchestration engine (ADR-001): it gives us an explicit **state machine**
with typed shared state, conditional edges, a **checkpointer** (memory + resumability),
**`interrupt`** (human-in-the-loop), and **`Send`** (dynamic fan-out for recursion) — all
first-class and all traced in LangSmith.

## 2. The graph

```
                                 ┌──────────────┐
                 ┌──────────────▶│  SUPERVISOR  │  intent · decompose · route
                 │               └──────┬───────┘
                 │        ┌─────────────┼───────────────┐
                 │        ▼             ▼               ▼
                 │  ┌───────────┐ ┌───────────┐  ┌───────────────┐
                 │  │ RETRIEVAL │ │ RESEARCH  │  │  DIRECT/CLARIFY│
                 │  │  agent    │ │ agent(RLM)│  │   (chit-chat / │
                 │  └─────┬─────┘ └─────┬─────┘  │  need more info)│
                 │        │             │        └───────┬────────┘
                 │        │   ┌─────────┘                │
                 │        ▼   ▼                          │
                 │   ┌────────────┐                      │
                 │   │ VALIDATION │ groundedness+guardrails
                 │   └─────┬──────┘                      │
                 │   retry │ ok                          │
                 └─────────┘  │                          │
                              ▼                          │
                      ┌───────────────┐                 │
                      │ HITL APPROVAL │ (only if high-risk tool) │
                      └───────┬───────┘                 │
                              ▼                          │
                        ┌──────────┐                     │
                        │ RESPONSE │◀────────────────────┘
                        └────┬─────┘
                             ▼
                            END
```

Conditional routing is done with LangGraph conditional edges driven by fields the Supervisor
writes into state (`route`, `needs_research`, `requires_approval`). Validation can loop back
to Retrieval/Research up to `MAX_RETRIES` (default 2) before forcing a graceful "I could not
verify this" response.

## 3. Specialized agents

### 3.1 Supervisor
- **Intent understanding:** classify the message (lookup · multi-hop research · analytics ·
  chit-chat · unsafe/blocked).
- **Task decomposition:** for complex asks, break into sub-questions and decide
  `needs_research`.
- **Routing:** set `route` ∈ {retrieval, research, direct, clarify}. Also decides which
  namespaces/filters are in scope given the user's role (so authorization shapes retrieval,
  not just blocks it).
- Emits `AgentEvent(node="supervisor", decision=...)`.

### 3.2 Retrieval agent
- For direct, single-hop questions. Calls the **Retrieval service** (hybrid + rerank),
  assembles context with attribution, and hands off to Validation.
- Keeps context small: top-k reranked **sections**, never whole documents (RLM1).

### 3.3 Research agent (the RLM engine)
See §4. For broad/multi-hop asks ("summarize all outage reports related to payment failures
last year and identify recurring root causes").

### 3.4 Validation agent
- **Groundedness:** is every claim supported by a retrieved chunk? (NLI-style check /
  LLM-as-judge with the evidence.)
- **Citation integrity:** every citation must resolve to a real retrieved `doc_id`
  (hallucinated-citation guardrail, S3).
- **Guardrail verdicts:** brand-safety, policy, PII.
- Outputs `verdict ∈ {pass, retry, block}` + reasons → drives the conditional edge.

### 3.5 Response agent
- Synthesizes the final answer from validated evidence, with inline citations, a short
  "reasoning" summary (F3), and streams tokens to the UI.

### 3.6 HITL approval node (bonus B2)
- For high-risk actions (e.g., an Administrator-only tool that would mutate data, or a
  low-confidence answer on a high-impact/restricted policy), the graph calls `interrupt()` and surfaces an
  approval request to the activity panel. The human approves/denies; state resumes from the
  checkpoint. No high-risk tool runs without the human edge when the policy flags it.

## 4. Recursive Language Model (RLM)

**Principle:** the model should *navigate* the corpus, not *ingest* it. The Research agent
implements the six behaviors from the brief:

1. **Explore document collections** — query Pinecone metadata to learn what document *types*,
   *departments*, and *date ranges* match the topic (cheap, no full text).
2. **Generate Python-based search plans** — the agent emits a **plan as code**: a small,
   schema-constrained Python structure (not free-form exec) describing batches, filters, and
   sub-questions. Example below. This is run by a **sandboxed plan interpreter**, not `eval`.
3. **Decompose large tasks** — split "last year's payment-failure outages" into monthly or
   per-incident batches so no single step needs the whole corpus.
4. **Retrieve targeted sections** — each batch pulls only the relevant **sections** (chunk
   granularity), with attribution.
5. **Call sub-agents recursively** — fan out one sub-agent per batch with LangGraph `Send`;
   each sub-agent can itself decompose further, bounded by `MAX_DEPTH` (default 2) and a
   global node budget (butterfly-effect guard, §6).
6. **Aggregate results** — a reduce node merges sub-answers, deduplicates root causes, and
   produces a structured synthesis handed to Validation → Response.

### 4.1 Plan-as-code (illustrative)

```python
# Produced by the Research agent, validated against a Pydantic schema, then interpreted.
plan = SearchPlan(
    objective="Recurring root causes of payment-failure outages in the last year",
    filters=Filters(document_type="incident", department="payments",
                    date_range=("2025-11-01", "2026-11-01")),
    strategy="map_reduce",
    batches=[  # one batch per month → one recursive sub-agent each
        Batch(key="2025-11", sub_question="payment-failure incidents in 2025-11, root cause?"),
        Batch(key="2025-12", sub_question="payment-failure incidents in 2025-12, root cause?"),
        # ...
    ],
    aggregation="cluster_root_causes_and_rank_by_frequency",
    max_depth=2,
)
```

### 4.2 Worked example (RLM8)

> **User:** "Summarize all outage reports related to payment failures during the last year
> and identify recurring root causes."

1. Supervisor → `route=research`, decompose into "find payment-failure outages" +
   "identify recurring root causes".
2. Research agent explores metadata: `document_type=incident ∧ department=payments ∧
   date in [last year]` → 37 matching incidents across 11 months.
3. Generates the plan above: `map_reduce`, one batch per month.
4. `Send` fans out 11 sub-agents (bounded). Each: targeted retrieval of that month's incident
   sections → summarize failures + extract candidate root causes. No sub-agent sees the whole
   corpus; each sees ~3–5 sections.
5. Aggregate: cluster root causes (e.g., *gateway timeout*, *expired cert*, *DB connection
   pool exhaustion*), rank by frequency, attach incident citations per cluster.
6. Validation checks each cluster is grounded in cited incidents; Response streams a ranked
   summary with citations and a one-line reasoning trace.

This is a **simplified-but-conceptually-complete** RLM, exactly as the brief allows: real
decomposition, real targeted retrieval, real bounded recursion, real aggregation.

## 5. Shared state (multi-agent collaboration, bonus B1)

LangGraph state is a typed `TypedDict`/Pydantic object; reducers define how concurrent
sub-agents merge their contributions safely.

```python
class AgentState(TypedDict):
    # conversation
    messages: Annotated[list[AnyMessage], add_messages]   # reducer: append
    session_id: str
    user: UserContext                                     # id + roles (from gateway, trusted)
    # routing / planning
    route: str | None
    plan: SearchPlan | None
    depth: int                                            # recursion depth guard
    node_budget: Annotated[int, take_min]                 # global butterfly-effect guard
    # evidence (concurrent-safe)
    evidence: Annotated[list[Chunk], merge_dedup_by_chunk_id]   # reducer: dedup-merge
    subanswers: Annotated[list[SubAnswer], operator.add]
    # control
    validation: Validation | None
    retries: int
    requires_approval: bool
    # output
    answer: str | None
    citations: list[Citation]
    errors: Annotated[list[AppError], operator.add]       # collected, never fatal mid-graph
```

Key choices:
- **Reducers make concurrency safe.** When N research sub-agents write `evidence`
  simultaneously, the `merge_dedup_by_chunk_id` reducer merges without clobbering — this is
  the "way agents manage state" the bonus asks about.
- **`errors` is accumulative, not throwing.** A sub-agent failure appends an `AppError` and
  returns partial results; the graph degrades rather than crashing (§6).
- **`node_budget`/`depth`** are shared ceilings so recursion cannot explode.

## 6. Failure handling & the "butterfly effect" (bonus B1)

A multi-agent graph with recursion can amplify a single failure (one flaky sub-agent → retry
storm → cascading timeouts → budget blown). We contain it:

| Risk | Control |
|------|---------|
| Runaway recursion | `MAX_DEPTH` + global `node_budget`; `Send` fan-out capped per level |
| One sub-agent fails | Isolated try/except per node → append `AppError`, return partial; aggregate uses whatever succeeded and notes coverage ("summarized 34/37 incidents") |
| Retry storms | Validation retries capped (`MAX_RETRIES`); exponential backoff with jitter on tool calls |
| Slow sub-agents | Per-node `asyncio.wait_for` timeout; late results dropped, not awaited forever |
| Partial retrieval | Response explicitly states coverage/limits rather than implying completeness |
| Poison input propagating | Guardrails run on retrieved content before it enters shared state (S2) |
| Cost/latency blowup | Node budget + rate limiting + model routing (cheap model for decomposition, strong model for synthesis) |

**Determinism & replay:** because state is checkpointed per node, any failed run can be
resumed or replayed from the last good checkpoint — critical for debugging the butterfly
effect in LangSmith.

## 7. Tools

| Tool | Purpose | Async | Role-gated (PEP) |
|------|---------|-------|------------------|
| `knowledge_search` | Hybrid retrieval over indexed docs (F1, T1) | ✅ | Viewer+ |
| `mcp.*` | Dummy enterprise data: employee directory, service catalog, incident records (T2) | ✅ | Analyst+ |
| `python_analysis` | Structured analysis on retrieved data in a sandbox (T3) | ✅ | Analyst+ |

- All tools run through the **Policy Enforcement Point**: the user's role (from the gateway,
  not the prompt) is checked **before** execution (S6, S7). A Viewer asking the model to "use
  the admin tool" fails at the PEP regardless of what the model decides.
- Tool execution is async with timeouts and circuit breakers (E3, E4).
- The **Python Analysis tool** executes in a restricted sandbox (no network, no filesystem
  writes, CPU/time limits) — it is never `eval` of model text.

## 8. Model routing (cost/quality)

- **Decomposition / planning / classification:** a fast, cheaper model.
- **Synthesis / final answer / validation-as-judge:** the strong primary model (Claude).
- Behind `libs/llm.LLMProvider`, so routing and provider are config, not code changes
  (ADR-003).

## 9. How the graph satisfies transparency (FE4–FE11)

Each node wraps its work in a context manager that: (a) opens a LangSmith span, (b) emits an
`AgentEvent` on entry (`node`), on each tool call (`tool`), on retrieval (`retrieval`), on
memory write (`memory`), and on validation (`validation`), and (c) streams `token` events
from the Response node and a final `final` event. The UI's **Agent Activity Panel** renders
this stream live, and the final event includes the LangSmith run URL so the evaluator can
open the full trace.
