---
doc_id: INC-2026-0421
title: Payment Gateway Timeout — 2026-04-21
department: payments
document_type: incident
access_level: internal
created_date: 2026-04-21
---

# Incident: Payment Gateway Timeout

## Summary
Payment submissions failed intermittently for ~40 min.

## Root Cause
Database connection pool exhaustion under peak load.

## Resolution
Increased pool size; added backpressure. (MOCK DATA for ABC Bank demo.)
