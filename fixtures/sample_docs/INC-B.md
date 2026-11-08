---
doc_id: INC-2025-1219
title: Payment Failure — expired TLS certificate
department: payments
document_type: incident
access_level: confidential
created_date: 2025-12-19
source_url: https://wiki.abcbank.internal/incidents/INC-2025-1219
---
# Incident INC-2025-1219

## Summary
Payments failed with TLS handshake errors (certificate has expired) for ~50 min.

## Root Cause
Expired TLS certificate on the gateway connector.

## Resolution
Rotated the certificate and added a 30-day expiry alert.
