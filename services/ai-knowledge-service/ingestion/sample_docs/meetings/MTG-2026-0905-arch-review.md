---
doc_id: MTG-2026-0905
title: Architecture Review — AI Assistant
department: platform
document_type: meeting
access_level: internal
created_date: 2026-09-05
version: 1.0
source_url: https://wiki.abcbank.internal/meetings/2026-09-05
---

# Architecture Review — AI Assistant (2026-09-05)

## Decisions
- Adopt LangGraph as the orchestration engine.
- Route all LLM calls through a model gateway for token metering and provider fallback.
- Enforce per-user monthly token budgets.

## Open Questions
Whether to split the knowledge service into separate read/write deployables (agreed: yes).
