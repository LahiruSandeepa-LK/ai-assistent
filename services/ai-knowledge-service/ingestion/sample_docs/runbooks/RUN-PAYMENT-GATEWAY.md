---
doc_id: RUN-PAYMENT-GATEWAY
title: Payment Gateway Runbook
department: payments
document_type: runbook
access_level: internal
created_date: 2025-09-25
version: 5.3
source_url: https://wiki.abcbank.internal/runbook/payment-gateway
---

# Payment Gateway Runbook

## When to use
Use this runbook when payment-api returns elevated HTTP 504 or 503 errors.

## Diagnose
1. Check the gateway connector dashboard for upstream latency > 3s (causes HTTP 504).
2. Check the ledger pool metric; `ERR_CONN_POOL` indicates connection pool exhaustion (HTTP 503).
3. Verify the TLS certificate expiry on the gateway connector (`openssl s_client`).

## Mitigate
- For pool exhaustion: scale ledger read replicas and raise `POOL_MAX` temporarily, then shed load.
- For upstream timeout: fail over to the secondary card-network endpoint.
- For expired certificate: rotate per RUN-CERT-ROTATION immediately.

## Escalation
Page the Payments on-call (SEV1 if customer-facing).
