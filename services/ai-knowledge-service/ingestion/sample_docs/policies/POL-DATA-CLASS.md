---
doc_id: POL-DATA-CLASS
title: Data Classification Policy
department: security
document_type: policy
access_level: internal
created_date: 2025-07-01
version: 2.1
source_url: https://wiki.abcbank.internal/policy/data-classification
---

# Data Classification Policy

## Purpose
Define how ABC Bank classifies and handles information across all systems.

## Classification Levels
| Level | Description | Examples | Handling |
|-------|-------------|----------|----------|
| Public | May be shared externally | Marketing pages | No restriction |
| Internal | Default for business data | Runbooks, architecture docs | Employees only |
| Confidential | Sensitive business data | Incident reports, roadmaps | Need-to-know |
| Restricted | Regulated / customer data | Account data, PII | Strict least-privilege |

## Access Rules
Access is granted by role (Viewer, Analyst, Administrator). Restricted data requires Administrator
approval and is never returned to the Viewer role. Metadata field `access_level` on every indexed
chunk enforces this at retrieval time.

## Review
This policy is reviewed every 12 months by the Information Security team.
