---
doc_id: POL-ACCESS-CONTROL
title: Access Control and RBAC Policy
department: security
document_type: policy
access_level: internal
created_date: 2025-08-15
version: 3.0
source_url: https://wiki.abcbank.internal/policy/access-control
---

# Access Control and RBAC Policy

## Roles
ABC Bank uses three application roles: **Viewer** (chat + search), **Analyst** (search + analytics +
MCP tools), and **Administrator** (all tools + document management).

## Principle of Least Privilege
Every tool and data access is checked server-side against the caller's role. The assistant must not
be able to bypass authorization through prompt instructions.

## Rate and Usage Limits
Each user has a per-minute request rate limit and a monthly token budget. When the token budget is
exhausted the user receives a "limit reached" message until the budget resets.

## Credentials
Service-to-service calls use short-lived tokens. Human users authenticate via Keycloak (OIDC).
