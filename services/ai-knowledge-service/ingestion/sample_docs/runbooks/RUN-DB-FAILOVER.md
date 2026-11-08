---
doc_id: RUN-DB-FAILOVER
title: Database Failover Runbook
department: platform
document_type: runbook
access_level: internal
created_date: 2025-08-30
version: 2.2
source_url: https://wiki.abcbank.internal/runbook/db-failover
---

# Database Failover Runbook

## Trigger
Primary PostgreSQL unreachable or replication lag > 60s.

## Steps
1. Confirm primary is down (not a network blip).
2. Promote the standby replica to primary.
3. Repoint the ledger-service connection string; restart pods.
4. Validate writes succeed and the connection pool is healthy.

## Rollback
If the old primary recovers with diverged data, keep the promoted node and reseed the old primary.
