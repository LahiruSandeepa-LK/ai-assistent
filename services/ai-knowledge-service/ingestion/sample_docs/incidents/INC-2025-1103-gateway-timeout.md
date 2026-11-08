---
doc_id: INC-2025-1103
title: Payment Failure Incident — Gateway upstream timeout
department: payments
document_type: incident
access_level: confidential
created_date: 2025-11-03
version: 1.0
source_url: https://wiki.abcbank.internal/incidents/INC-2025-1103
---

# Incident INC-2025-1103: Gateway upstream timeout

## Summary
payment-api returned HTTP 504 for ~35 min. The gateway connector saw upstream latency spike to 8s, exceeding the 3s timeout.

## Impact
Customer-facing payment failures (SEV1).

## Root Cause
gateway timeout.

## Resolution
Failed over to the secondary card-network endpoint.

## Action Items
- Review related runbook and add/verify preventive alerting.
- Track recurrence for trend analysis.
