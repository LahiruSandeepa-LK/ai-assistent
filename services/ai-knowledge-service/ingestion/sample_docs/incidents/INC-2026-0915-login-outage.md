---
doc_id: INC-2026-0915
title: Login Outage — Keycloak overload
department: platform
document_type: incident
access_level: confidential
created_date: 2026-09-15
version: 1.0
source_url: https://wiki.abcbank.internal/incidents/INC-2026-0915
---

# Incident INC-2026-0915: Login Outage

## Summary
Users could not sign in for ~15 min; Keycloak CPU saturated after a token-storm from a misbehaving client.

## Root Cause
Unbounded token refresh from a mobile client build; no per-client rate limit.

## Resolution
Added per-client rate limiting; scaled Keycloak. Not related to the payments platform.
