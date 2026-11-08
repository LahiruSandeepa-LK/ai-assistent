---
doc_id: ARCH-PAYMENTS-PLATFORM
title: Payments Platform Architecture
department: payments
document_type: architecture
access_level: confidential
created_date: 2025-09-20
version: 4.2
source_url: https://wiki.abcbank.internal/arch/payments-platform
---

# Payments Platform Architecture

## Overview
The payments platform processes card and account-to-account transactions. It is composed of the
Payment API, the Payment Gateway connector, a ledger service, and an async settlement pipeline.

## Components
- **payment-api**: validates and orchestrates a payment request.
- **payment-gateway-connector**: talks to the external card network over TLS.
- **ledger-service**: double-entry ledger, backed by PostgreSQL with a bounded connection pool.
- **settlement-worker**: batch settlement via a message queue.

## Known Constraints
The ledger PostgreSQL connection pool is capped at 100 connections. Under peak load, exhaustion of
this pool (error `ERR_CONN_POOL`) causes HTTP 503 responses from payment-api. The gateway connector
enforces a 3-second upstream timeout; exceeding it returns HTTP 504.

## Scaling
payment-api is stateless and scales horizontally. The ledger is the primary bottleneck and is
scaled vertically with read replicas for reporting.
