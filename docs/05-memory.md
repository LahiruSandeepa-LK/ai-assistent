# 05 — Memory Architecture

> Covers requirements M1–M6 and bonus **Long-term memory (B4)**. The brief asks us to
> *explain memory design decisions* — this document is that explanation. See ADR-006.

## 1. Two-tier memory

| Tier | Scope | Store | Purpose |
|------|-------|-------|---------|
| **Short-term (working)** | One session/thread | LangGraph checkpointer on **Redis** | Multi-turn context: previous questions, running state, tool outputs (M2, M3, M5) |
| **Long-term (durable)** | Across sessions, per user | **Postgres** + vector memory index | Relevant historical interactions, durable user context/preferences (M4) |

We deliberately separate them because they have different lifetimes, consistency needs, and
privacy implications.

## 2. Short-term memory (M2, M3, M5)

- Implemented with LangGraph's **checkpointer** keyed by `thread_id = session_id`. After every
  node, state (messages, evidence, plan, …) is persisted. This is what makes memory "survive
  multiple turns during a session" (M5) and makes any agent replica able to resume a thread.
- **Context-window management:** we don't replay the raw transcript forever. A **summary
  buffer** keeps the last *N* turns verbatim plus a rolling LLM summary of older turns. This
  bounds token cost and latency while preserving continuity — and it is itself a small RLM
  idea (summarize rather than stuff).
- Redis is chosen for the checkpointer because it is fast, already present for rate limiting
  and caching, and session memory is ephemeral by nature (TTL on the thread).

## 3. Long-term memory (M4, bonus B4)

- After a session (or on explicit "remember this"), a **memory writer** distills durable
  facts: user's role/team, recurring topics, stable preferences ("always cite incident IDs"),
  and summaries of notable Q&A. These are written to Postgres (structured) and embedded into a
  **per-user memory namespace** in the vector store (semantic recall).
- On a new session, the Supervisor does a cheap **memory retrieval**: fetch the user's profile
  row + top-k semantically-relevant past interactions for the current query, and inject a
  compact "what we know about this user / past context" block.
- **Privacy & scope:** long-term memory is per-user and never crosses users; it stores
  summaries and preferences, not raw personal content; it is subject to the same RBAC and is
  purgeable on request. (A good default for any enterprise deployment, e.g. the ABC Bank persona.)

## 4. Memory events (transparency, FE8)

Every memory read/write emits `AgentEvent(type="memory", op="read"|"write", summary=...)` so
the activity panel shows memory updates live and LangSmith records them.

## 5. Design decisions & rationale (M6)

1. **Checkpointer over ad-hoc message lists.** Using LangGraph's checkpointer (not a hand-rolled
   list in the UI) means memory, resumability, and HITL all share one durable mechanism, and
   state survives a crash mid-graph.
2. **Redis for short-term, Postgres+vector for long-term.** Match store to lifetime: ephemeral
   fast store for session state; durable relational + semantic store for cross-session recall.
3. **Summary buffer, not infinite transcript.** Controls cost/latency and keeps the model
   focused; aligns with the RLM "don't stuff context" philosophy.
4. **Separate durable fact extraction.** We don't blindly persist whole conversations; we
   extract durable, useful facts, which keeps long-term memory small, relevant, and privacy-safe.
5. **Memory is observable and governable.** Reads/writes are traced and the store is
   per-user, scoped, and purgeable — important for any enterprise deployment.

## 6. Trade-offs

- **Richer long-term memory (e.g., a full knowledge graph of the user)** would improve
  personalization but adds complexity and privacy surface; for the POC we keep profile +
  semantic recall. Revisit if personalization becomes a product goal.
- **Summary buffer can lose detail** older than the window; mitigated by long-term recall and
  by the fact that source documents (not chat history) are the ground truth for answers.
