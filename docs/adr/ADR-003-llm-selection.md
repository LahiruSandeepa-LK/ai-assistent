# ADR-003: LLM selection and provider abstraction

**Status:** Accepted · **Date:** 2026-11-08 · **Deciders:** AI Lead

## Context
The brief allows any modern LLM but requires documented model-selection rationale, and the
error-handling requirement implies we must survive an LLM outage. Agentic workloads are
cost/latency sensitive.

## Decision
Use **Anthropic Claude as the primary LLM**, **OpenAI as a fallback**, and **managed
embeddings**, all behind an `LLMProvider` interface in `libs/llm`. Route cheap tasks
(classification, decomposition) to a fast model and expensive tasks (synthesis, validation) to
the strong model.

## Options Considered
### Option A: Claude primary + OpenAI fallback (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low–Medium |
| Cost | Controlled via model routing |
| Scalability | High (managed) |
| Reasoning/tool-use | Strong |

**Pros:** strong multi-step reasoning + tool use for Supervisor/RLM; robust under adversarial
input (helps injection defense); reliable structured output; resilience via fallback. **Cons:**
two vendor keys; prompt nuances differ per provider.

### Option B: Single provider
**Pros:** simpler. **Cons:** no resilience to an outage (fails E1).

### Option C: Self-hosted open-source LLM
**Pros:** data control, no per-token cost. **Cons:** GPU ops; weaker tool-use for a POC;
slower to stand up. Kept as a future option behind the interface.

## Trade-off Analysis
A provider interface + fallback costs a little abstraction now and buys resilience + swapability
later. Model routing is the main cost lever for agentic systems and is nearly free to add.

## Consequences
- Easier: switching/adding providers; controlling cost/latency.
- Harder: prompt tuning must be validated per provider (fallback path tested).
- Revisit: self-hosted model for production data-control requirements.

## Action Items
1. [ ] `LLMProvider` interface + Anthropic/OpenAI adapters.
2. [ ] Config-driven model routing (fast vs strong).
3. [ ] Fallback-path integration test (kill primary).

## Addendum (2026-11-09): provider adapters
All LLM calls go through `ai-model-gateway` / `libs/llm`. Providers are pluggable via
`LLM_PROVIDER` (gemini | anthropic | openai | mock) with per-provider `*_MODEL_STRONG/FAST`
env vars and an optional `LLM_FALLBACK`. Adapters: `libs/llm/provider_gemini.py`,
`provider_anthropic.py`, `provider_openai.py` — each implements one `complete()` method and
reports real token usage to the budget. Adding a model = one new `provider_*.py` + a line in
`get_provider()`. Model slugs are env-overridable because they change frequently.
