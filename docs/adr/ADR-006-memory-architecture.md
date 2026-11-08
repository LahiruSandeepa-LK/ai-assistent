# ADR-006: Two-tier memory (Redis checkpointer + Postgres/vector)

**Status:** Accepted · **Date:** 2026-11-08 · **Deciders:** AI Lead

## Context
Memory must maintain user context, previous questions, and relevant historical interactions,
survive multiple turns per session, and the design must be explained. Bonus: long-term memory.

## Decision
**Short-term** memory via a **LangGraph checkpointer on Redis** (keyed by `session_id`) with a
summary buffer; **long-term** memory via **Postgres** (profile/facts/feedback/audit) + a
**per-user vector memory namespace** for semantic recall.

## Options Considered
### Option A: Two-tier Redis + Postgres/vector (chosen)
**Pros:** matches store to lifetime (ephemeral vs durable); checkpointer unifies memory +
resumability + HITL; semantic recall for cross-session relevance. **Cons:** two stores.

### Option B: Everything in Postgres
**Pros:** one store. **Cons:** slower session-state churn; no native semantic recall.

### Option C: UI-side message list only
**Pros:** trivial. **Cons:** no durability/resumability; loses state on crash; no long-term
memory; fails M4/M5 robustly.

## Trade-off Analysis
The two-tier split adds a store but gives the right durability/latency per use case and reuses
Redis (already present for cache/rate-limit) and Postgres (already present for Keycloak/audit).

## Consequences
- Easier: resumable sessions, cross-session personalization, observability of memory ops.
- Harder: memory governance (privacy/purge) — addressed with per-user scope + purge.
- Revisit: knowledge-graph memory if personalization becomes a product goal.

## Action Items
1. [ ] Redis checkpointer + summary buffer.
2. [ ] Postgres schema (profile, facts, feedback, audit) + per-user vector namespace.
3. [ ] Memory read/write `AgentEvent`s + purge endpoint.
