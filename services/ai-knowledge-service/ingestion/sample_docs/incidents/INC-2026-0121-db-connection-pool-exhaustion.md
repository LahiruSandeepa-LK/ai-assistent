---
doc_id: INC-2026-0121
title: Payment Failure Incident — Ledger connection pool exhaustion
department: payments
document_type: incident
access_level: confidential
created_date: 2026-01-21
version: 1.0
source_url: https://wiki.abcbank.internal/incidents/INC-2026-0121
---

# Incident INC-2026-0121: Ledger connection pool exhaustion

## Summary
payment-api returned HTTP 503 with `ERR_CONN_POOL` under peak load; ledger pool hit its 100-connection cap for ~40 min.

## Impact
Customer-facing payment failures (SEV1).

## Root Cause
db connection pool exhaustion.

## Resolution
Scaled read replicas and raised POOL_MAX; shed non-critical load.

## Action Items
- Review related runbook and add/verify preventive alerting.
- Track recurrence for trend analysis.
