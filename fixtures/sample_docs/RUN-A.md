---
doc_id: RUN-PAYMENT-GATEWAY
title: Payment Gateway Runbook
department: payments
document_type: runbook
access_level: internal
created_date: 2025-09-25
source_url: https://wiki.abcbank.internal/runbook/payment-gateway
---
# Payment Gateway Runbook

## Diagnose
HTTP 504 means upstream latency over 3s. ERR_CONN_POOL (HTTP 503) means pool exhaustion.

## Mitigate
For pool exhaustion scale read replicas and raise POOL_MAX. For timeout fail over to secondary endpoint.
