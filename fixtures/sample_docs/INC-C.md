---
doc_id: INC-2026-0304
title: Payment Failure — gateway upstream timeout
department: payments
document_type: incident
access_level: confidential
created_date: 2026-03-04
source_url: https://wiki.abcbank.internal/incidents/INC-2026-0304
---
# Incident INC-2026-0304

## Summary
Recurrence of upstream latency causing HTTP 504 for ~25 min.

## Root Cause
Gateway upstream timeout during a card-network degradation.

## Resolution
Failed over to the secondary card-network endpoint.
