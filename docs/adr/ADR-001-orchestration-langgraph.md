# ADR-001: Use LangGraph as the orchestration engine

**Status:** Accepted · **Date:** 2026-11-08 · **Deciders:** AI Lead, Backend Lead

## Context
We need a multi-agent orchestrator that supports specialized agents, conditional routing,
shared state, recursion (RLM), human-in-the-loop, memory/resumability, and deep tracing. The
brief also mandates LangGraph and LangSmith.

## Decision
Use **LangGraph** (`StateGraph`) as the orchestration engine, with a Redis checkpointer,
`interrupt()` for HITL, and `Send` for recursive fan-out; trace everything in **LangSmith**.

## Options Considered
### Option A: LangGraph
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium |
| Cost | Low (OSS) |
| Scalability | Good (stateless nodes + external checkpointer) |
| Team familiarity | Good; LangChain ecosystem |

**Pros:** explicit state machine; checkpointer = memory + resumability; `interrupt`/`Send`
built-in; native LangSmith tracing; mandated. **Cons:** opinionated; graph can get complex.

### Option B: Custom asyncio orchestration
| Dimension | Assessment |
|-----------|------------|
| Complexity | High |
| Cost | High (build+maintain) |
| Scalability | DIY |
| Team familiarity | N/A |

**Pros:** full control. **Cons:** reinvents checkpointing, interrupt, fan-out, tracing;
contradicts the brief.

### Option C: Plain LangChain agents / AgentExecutor
**Pros:** quick. **Cons:** weak explicit state/graph control, harder to trace transitions and
to implement bounded recursion and HITL.

## Trade-off Analysis
LangGraph trades some flexibility for a large amount of built-in capability that directly maps
to graded requirements (transitions, HITL, memory, tracing). Building these ourselves (B)
would dominate the 12-day budget.

## Consequences
- Easier: transitions, memory, HITL, recursion, tracing.
- Harder: graph complexity must be managed with clear node/edge modules.
- Revisit: if graphs balloon, extract subgraphs (already done for Research/RLM).

## Action Items
1. [ ] `StateGraph` with typed state + reducers.
2. [ ] Redis checkpointer; `interrupt` for HITL; `Send` for RLM fan-out.
3. [ ] LangSmith project per env.
