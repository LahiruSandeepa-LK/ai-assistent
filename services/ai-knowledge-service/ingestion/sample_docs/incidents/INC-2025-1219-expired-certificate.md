---
doc_id: INC-2025-1219
title: Payment Failure Incident — Expired TLS certificate on gateway
department: payments
document_type: incident
access_level: confidential
created_date: 2025-12-19
version: 1.0
source_url: https://wiki.abcbank.internal/incidents/INC-2025-1219
---

# Incident INC-2025-1219: Expired TLS certificate on gateway

## Summary
Payments failed with TLS handshake errors (`certificate has expired`) on CN gateway.cardnet.abcbank for ~50 min.

## Impact
Customer-facing payment failures (SEV1).

## Root Cause
expired certificate.

## Resolution
Rotated the certificate per RUN-CERT-ROTATION; added 30-day expiry alert.

## Action Items
- Review related runbook and add/verify preventive alerting.
- Track recurrence for trend analysis.
