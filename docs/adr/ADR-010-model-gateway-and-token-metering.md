# ADR-010: Centralize LLM calls in a model gateway for token metering

**Status:** Accepted · **Date:** 2026-11-09 · **Deciders:** AI Lead

## Context
Per-user **token budgets** are a hard requirement: each user has an LLM token quota (kept in
Redis), we must reject work when it's exhausted, and we must account for every token for cost
control and analytics. We also already want provider fallback (ADR-003) and fast/strong model
routing. The question is *where* LLM calls happen.

## Decision
Route **all** LLM calls through a dedicated **ai-model-gateway** service. It owns provider
routing + fallback, fast/strong model selection, and **token metering**: after each call it
reports `prompt_tokens + completion_tokens` to ai-conversation-service (Redis usage) and a
Postgres ledger. The orchestrator no longer calls providers directly. The **pre-flight budget
check** stays at ai-assistant-api (fail fast); the **post-flight accounting** happens in the
gateway (can't be bypassed).

## Options Considered
### Option A: Model gateway service (chosen)
| Dimension | Assessment |
|-----------|------------|
| Metering integrity | High — one choke point, no bypass |
| Latency | +1 internal hop |
| Cost control | Central caps, fallback, routing in one place |

**Pros:** token metering and caps can't leak; provider fallback + model routing centralized;
one place to add caching, retries, circuit breaking for LLM calls. **Cons:** an extra hop and a
service to run.

### Option B: Shared `libs/llm` library (meter after each call)
**Pros:** no extra hop. **Cons:** every service/code path must remember to record usage; easy to
leak a call that isn't metered — weak for a *hard* budget requirement.

### Option C: Meter only at the edge (estimate)
**Pros:** simplest. **Cons:** estimates drift from real usage; no per-call accounting.

## Trade-off Analysis
A hard, per-user token budget needs a place it cannot be bypassed. A library (B) relies on
discipline; the gateway (A) enforces by topology. The extra hop is cheap relative to the LLM
call itself, and the gateway becomes the natural home for fallback, routing, and LLM-level
caching/retries.

## Consequences
- Easier: tamper-proof token accounting, central cost caps, provider fallback, model routing.
- Harder: one more service; a hop on the hot path (mitigated: it's thin and co-located).
- Revisit: collapse back to a library for a tiny single-tenant deployment where budgets don't
  matter.

## Action Items
1. [ ] ai-model-gateway: `/complete`, `/stream`, provider router + fallback, model selection.
2. [ ] Post-call metering → ai-conversation-service usage (Redis) + Postgres ledger.
3. [ ] ai-assistant-api pre-flight budget check; graceful "limit reached" message.
4. [ ] ai-admin-service analytics over the ledger (cost/tokens per user & feature).
