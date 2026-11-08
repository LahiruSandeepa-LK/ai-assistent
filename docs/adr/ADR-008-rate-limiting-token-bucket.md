# ADR-008: Token-bucket rate limiting in Redis

**Status:** Accepted · **Date:** 2026-11-08 · **Deciders:** AI Lead, Platform

## Context
The brief requires token-bucket rate limiting with per-user limits, configurable thresholds, and
graceful error handling. Limits must hold across multiple gateway replicas, and we also want to
protect the LLM budget.

## Decision
Implement **token bucket per user and per role tier**, stored in **Redis** with an atomic Lua
check-and-decrement. Thresholds (`capacity`, `refill_rate`) are configurable per role via env.
On exhaustion return `429 + Retry-After`; the UI degrades gracefully.

## Options Considered
### Option A: Token bucket in Redis (chosen)
| Dimension | Assessment |
|-----------|------------|
| Burst handling | Good (bucket allows short bursts) |
| Distributed correctness | Good (atomic Lua) |
| Complexity | Low |

**Pros:** mandated algorithm; smooths bursts while capping sustained rate; atomic + shared
across replicas; same store as cache/checkpointer. **Cons:** Redis is on the request path (already
required anyway).

### Option B: Fixed-window counter
**Pros:** trivial. **Cons:** boundary bursts; not the requested algorithm.

### Option C: In-process limiter
**Pros:** no Redis call. **Cons:** wrong across replicas; state lost on restart.

## Trade-off Analysis
Token bucket in Redis is the requested algorithm and the only option that is both burst-friendly
and correct across replicas. The Redis dependency is already present.

## Consequences
- Easier: per-user/role limits, configurable, distributed-correct; doubles as LLM-budget guard.
- Harder: tuning thresholds (exposed as config; informed by metrics).
- Revisit: add global and per-IP buckets if abuse patterns emerge.

## Action Items
1. [ ] Redis Lua token-bucket; per-role config (`RATE_LIMIT_*`).
2. [ ] `429 + Retry-After`; friendly UI handling; `rate_limit_hits` metric.
