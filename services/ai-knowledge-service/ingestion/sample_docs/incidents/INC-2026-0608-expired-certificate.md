---
doc_id: INC-2026-0608
title: Payment Failure Incident — Expired TLS certificate (recurrence)
department: payments
document_type: incident
access_level: confidential
created_date: 2026-06-08
version: 1.0
source_url: https://wiki.abcbank.internal/incidents/INC-2026-0608
---

# Incident INC-2026-0608: Expired TLS certificate (recurrence)

## Summary
A secondary gateway endpoint certificate expired; partial payment failures for ~20 min.

## Impact
Customer-facing payment failures (SEV1).

## Root Cause
expired certificate.

## Resolution
Rotated cert; extended the expiry alert to all gateway endpoints.

## Action Items
- Review related runbook and add/verify preventive alerting.
- Track recurrence for trend analysis.
