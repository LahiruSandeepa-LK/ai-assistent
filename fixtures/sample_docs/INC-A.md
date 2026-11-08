---
doc_id: INC-2026-0121
title: Payment Failure — connection pool exhaustion
department: payments
document_type: incident
access_level: confidential
created_date: 2026-01-21
source_url: https://wiki.abcbank.internal/incidents/INC-2026-0121
---
# Incident INC-2026-0121

## Summary
payment-api returned HTTP 503 with ERR_CONN_POOL under peak load for ~40 min.

## Root Cause
Ledger PostgreSQL connection pool exhaustion.

## Resolution
Scaled read replicas and raised POOL_MAX; shed non-critical load.
