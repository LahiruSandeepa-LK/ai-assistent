---
doc_id: POL-INCIDENT-MGMT
title: Incident Management Policy
department: operations
document_type: policy
access_level: internal
created_date: 2025-06-10
version: 1.4
source_url: https://wiki.abcbank.internal/policy/incident-management
---

# Incident Management Policy

## Severity Levels
- **SEV1**: customer-facing outage (e.g., payments down). Page on-call immediately.
- **SEV2**: degraded service, workaround exists.
- **SEV3**: minor issue, no customer impact.

## Process
1. Declare incident and assign an Incident Commander.
2. Mitigate first, diagnose second.
3. Post a status update every 30 minutes for SEV1.
4. Write a blameless postmortem within 5 business days.

## Postmortem Requirements
Every SEV1/SEV2 postmortem must capture: timeline, root cause, contributing factors, and action
items with owners. Postmortems are classified Confidential.
