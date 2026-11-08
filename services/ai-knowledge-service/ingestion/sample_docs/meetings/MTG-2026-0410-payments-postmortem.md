---
doc_id: MTG-2026-0410
title: Payments Reliability Review — Meeting Notes
department: payments
document_type: meeting
access_level: confidential
created_date: 2026-04-10
version: 1.0
source_url: https://wiki.abcbank.internal/meetings/2026-04-10
---

# Payments Reliability Review (2026-04-10)

## Attendees
Payments SRE, Platform, Product.

## Discussion
Reviewed recurring payment failures: gateway timeouts and recurring expired-certificate outages.
Agreed the biggest recurring root causes over the last two quarters are (1) upstream gateway
timeouts and (2) expired TLS certificates.

## Decisions
- D1: Make the 30-day cert-expiry alert mandatory on ALL gateway endpoints. (owner: Platform)
- D2: Add automatic failover to the secondary card-network endpoint. (owner: Payments SRE)
- D3: Raise ledger `POOL_MAX` and add autoscaling of read replicas. (owner: Platform)

## Action Items
Track recurrence in the incident namespace for the next quarter.
