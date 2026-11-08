# 14 — Token Budget, Memory Cadence & Cost Control

How the system stays cheap and coherent over long sessions: a **per-user token budget**, a
**router that skips RAG/tools** when possible, **summarize-after-N** memory, and a **semantic
cache**. Owned mostly by **ai-conversation-service**; LLM metering by **ai-model-gateway**.
See ADR-010 and `diagrams/request-flow-token-budget.drawio`.

## 1. Per-user token budget (hard requirement)

Keep it distinct from rate limiting — they are two different controls:

| Control | Protects | Shape | On breach |
|---------|----------|-------|-----------|
| Rate limit (token bucket) | throughput / bursts | requests per minute | `429`, retry shortly |
| **Token budget (quota)** | **LLM cost** | cumulative tokens per day/month | hard stop, "limit reached" |

**Data (Redis), owned by ai-conversation-service:**
```
usage:{user_id}:{period}  ->  { limit, used, reset_at }      # period = daily|monthly, per role
```
Defaults (configurable, `.env`): Viewer 200k, Analyst 1M, Admin 5M tokens / month.

**Two-phase enforcement** (you only know real usage *after* the call):
```
PRE  — ai-assistant-api, before any work:
      remaining = limit - used
      if remaining <= 0  -> STOP, return chat message:
         "You've reached your token limit for this {period}. It resets {reset_at}."
      (no LLM, no RAG, no tools — cheapest possible rejection)

POST — ai-model-gateway, after each LLM call:
      actual = response.usage.prompt_tokens + completion_tokens
      -> ai-conversation-service: INCRBY used += actual      (atomic, Redis)
      -> append to Postgres usage ledger                     (durable; ai-admin-service analytics)
```
- **Streaming:** accumulate completion tokens as they stream; finalize at end; optionally abort
  mid-stream if the cap is crossed.
- **Concurrency:** optionally *reserve* an estimate pre-flight and reconcile post-flight if a
  user fires many parallel turns.
- **Why ai-model-gateway does the POST:** all LLM calls funnel through it, so metering can't be
  bypassed by any code path (ADR-010).

## 2. The router skips expensive layers

The orchestrator's first node classifies the turn and avoids RAG/tools when it can. Order is
chosen so the cheapest exits come first:

```
token gate (api) -> cache hit? -> answerable-from-context? -> else route (RAG | tool | research)
```

| Mechanism | Catches | Where | Saves |
|-----------|---------|-------|-------|
| **Semantic cache** | near-duplicate query asked before (any session) | ai-conversation-service (embed query → similarity ≥ threshold on recent Q→A) | RAG + tools + maybe the LLM entirely |
| **Answer-from-context** | in-session follow-up ("what did I just ask?", "summarize that") | ai-orchestrator router (answerable from loaded history) | RAG + tools (1 cheap LLM call) |
| **Model routing** | cheap tasks vs hard tasks | ai-model-gateway | fast model for classify/decompose/summarize; strong model for synthesis |

Cache threshold `SEMANTIC_CACHE_THRESHOLD=0.95` (configurable). A cache hit still passes the
output guardrail before returning.

## 3. Memory cadence — summarize after N queries

Short-term memory must stay small or every prompt grows unbounded.

```
keep last VERBATIM_TURNS (=6) turns verbatim
+ a rolling summary of everything older
every SUMMARIZE_EVERY_N_TURNS (=10) user queries:
    fold the older block into the rolling summary  — ASYNC, off the response path, cheap model
```
System prompt each turn = `rolling summary` + `last 6 turns` + `long-term profile`. This keeps the
assistant coherent across long sessions **without re-sending the whole transcript** (the main
cost driver), and the user never waits for summarization because it runs asynchronously.

Long-term memory (profile, prior decisions) is extracted deliberately at session end — not every
turn — to keep it relevant and privacy-safe (`docs/05-memory.md`).

## 4. Cost-control summary (what keeps API spend down)

1. **Token-budget gate** — the broke user does zero work.
2. **Cache + answer-from-context** — repeats and follow-ups skip RAG/tools/strong model.
3. **Summarize-after-10** — bounded prompt size over long sessions.
4. **Model routing** — cheap model for the 80% of calls that don't need the strong one.
5. **Retrieval before generation** — fetch targeted sections (RLM) instead of stuffing context.
6. **Embedding + query caching** — avoid re-embedding repeated queries.
7. **Metering + ledger** — ai-model-gateway records every token so ai-admin-service can show
   cost per user / per feature and catch runaway spend.

## 5. Trade-offs

- **Model-gateway hop** adds latency vs a shared library, but is the clean place to meter tokens
  and enforce caps (ADR-010); worth it given the budget requirement.
- **Semantic cache** risks a stale/near-miss answer; mitigated by a high similarity threshold and
  still running the output guardrail. Short TTL keeps it fresh.
- **Aggressive summarization** can drop older detail; mitigated by long-term memory and by the
  fact that source documents (not chat history) are the ground truth for answers.
