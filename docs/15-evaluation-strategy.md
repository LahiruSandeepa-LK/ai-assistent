# 15 — Evaluation & Accuracy Measurement

How we measure whether the assistant is *accurate* — at three layers, offline (regression gate)
and online (production). Owned by **ai-admin-service** (`eval/`), scored with **LangSmith**
datasets + evaluators. See `diagrams/evaluation-pipeline.drawio`.

## 1. The golden set (prerequisite)

A curated dataset of `question → expected source doc/chunk ids → reference answer`. Start with
30–50 Q&A spanning each document type; grow it from production feedback. Stored as a LangSmith
dataset (sample seed: `services/ai-admin-service/eval/golden_set.sample.jsonl`). Without it,
every "is it accurate?" claim is just vibes.

## 2. Layer 1 — Retrieval quality (did we fetch the right chunks?)

| Metric | Definition | POC target |
|--------|------------|-----------|
| Recall@k | % questions with a relevant chunk in top-k | ≥ 0.90 @k=6 |
| MRR | mean reciprocal rank of first relevant chunk | ≥ 0.75 |
| nDCG@k | rank-weighted relevance | ≥ 0.70 |
| Context precision | fraction of retrieved chunks that are relevant | ≥ 0.6 |

Requires relevance labels (which chunk truly answers each question) from the golden set.

## 3. Layer 2 — Generation quality (is the answer right and grounded?)

RAGAS-style, scored by **LLM-as-judge** + human spot-check:

| Metric | Answers | How |
|--------|---------|-----|
| **Faithfulness / groundedness** | is every claim supported by retrieved context? | decompose answer → claims → NLI/judge each vs context |
| **Answer relevance** | does it address the question? | judge question ↔ answer |
| **Citation accuracy** | do cited sources exist and support the claim? | resolve each citation to a retrieved `doc_id` |
| **Correctness** | matches the reference answer? | judge vs golden answer with a rubric |
| **Hallucination rate** | % answers with an unsupported claim | 1 − faithfulness pass; target < 3% |

## 4. Layer 3 — Agent / system quality

Routing accuracy (did the router pick the right path: cache / context / RAG / tool / research?),
tool-selection accuracy, task success rate, **p95 latency**, and **cost + tokens per answer**
(from the ai-model-gateway ledger).

## 5. Online (production) signals

Thumbs up/down + comment (feedback store) → deflection rate, escalation/refusal correctness,
and new rows for the golden set. Feedback closes the loop: traces → feedback → dataset → eval →
improvement.

## 6. Two cadences, one concept

| | Online (live) | Offline (batch) |
|--|---------------|-----------------|
| Where | ai-orchestrator **Validation node** | ai-admin-service **eval harness** |
| What | faithfulness + citation check on *every real answer* (guardrail) | full L1+L2+L3 suite on the golden set |
| When | per request | on every change to prompts / chunking / retrieval / rerank / model |
| Gate | blocks a bad answer to the user | **blocks a merge** in CI if a metric regresses |

## 7. The pipeline

```
golden set (LangSmith dataset)
      │  on change to prompt/chunking/retrieval/rerank/model:
      ▼
ai-admin-service eval/run_eval.py  → runs set through ai-knowledge-service + ai-orchestrator
      │                              → LangSmith evaluators compute L1 + L2 + L3
      ▼
CI gate: fail build if faithfulness < target OR Recall@k drops
      │
      ▼
ui-admin dashboard (scores, trends)   ◄── production feedback feeds new golden rows
```

## 8. Targets to ship the POC

Recall@6 ≥ 0.90, faithfulness ≥ 0.97 (hallucination < 3%), citation accuracy = 100% (every
citation resolves), routing accuracy ≥ 0.9, and cost/answer tracked per user. These are
design targets; the POC validates them against the golden set before the demo.
