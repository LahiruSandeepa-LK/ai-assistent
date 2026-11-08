---
doc_id: ARCH-AUTH
title: Authentication and Authorization Architecture
department: platform
document_type: architecture
access_level: internal
created_date: 2025-10-05
version: 2.0
source_url: https://wiki.abcbank.internal/arch/auth
---

# Authentication and Authorization Architecture

## Identity
ABC Bank uses Keycloak as the OIDC identity provider. Access tokens are JWTs carrying
`realm_access.roles`. Tokens are validated at the edge using the JWKS endpoint.

## Authorization
A Policy Enforcement Point evaluates `(roles, action, resource)` before every tool call and before
retrieval. Document `access_level` is intersected with the caller's clearance so restricted content
is never retrieved for lower roles.

## Sessions
Sessions are identified by `session_id`; conversation state is held in Redis and survives for the
session lifetime.
