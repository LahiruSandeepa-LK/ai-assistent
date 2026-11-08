---
doc_id: SPEC-INSTANT-TRANSFER
title: Instant Transfer Feature Specification
department: product
document_type: spec
access_level: confidential
created_date: 2026-02-10
version: 0.9
source_url: https://wiki.abcbank.internal/specs/instant-transfer
---

# Instant Transfer — Feature Specification

## Goal
Let customers move money between ABC Bank accounts in under 5 seconds, 24/7.

## Requirements
- Idempotent transfer API keyed by a client-supplied `transfer_id`.
- Hard limit of $25,000 per transfer for the Viewer tier.
- Full audit trail in the ledger.

## Non-Goals
External bank transfers (handled by the existing ACH batch).

## Success Metrics
p95 completion < 5s; failure rate < 0.1%.
