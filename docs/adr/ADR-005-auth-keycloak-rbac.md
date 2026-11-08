# ADR-005: Authentication & RBAC via Keycloak

**Status:** Accepted · **Date:** 2026-11-08 · **Deciders:** AI Lead, Security

## Context
The brief offers Option A (hardcoded users) or Option B (open-source auth, e.g., Keycloak) and
grades RBAC and "the agent cannot bypass authorization". Three roles: Viewer, Analyst,
Administrator; tool execution must respect roles.

## Decision
Use **Keycloak (Option B)** as an OIDC identity provider; the gateway validates JWTs and reads
role claims; a **Policy Enforcement Point** in the agent checks `(roles, action, resource)`
before every tool/retrieval. Provide a **hardcoded dev mode** (`AUTH_MODE=dev`) as a fallback
so the system runs without Keycloak locally.

## Options Considered
### Option A: Hardcoded users/roles
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Realism | Low |
| Grading fit | Partial |

**Pros:** trivial; no extra container. **Cons:** not real authz; weaker demonstration of
"no bypass".

### Option B: Keycloak (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium |
| Realism | High |
| Grading fit | Strong |

**Pros:** real OIDC tokens + role claims; realm import for reproducibility; demonstrates proper
enterprise authz. **Cons:** one more service to run/configure.

## Trade-off Analysis
Keycloak costs one container and some config but directly strengthens a graded area; the dev
override removes the local-friction downside.

## Consequences
- Easier: realistic RBAC; defensible "no authz bypass" story (server-side PEP).
- Harder: Keycloak realm/config maintenance.
- Revisit: SSO federation for production.

## Action Items
1. [ ] Keycloak realm `ai-assistant` with roles Viewer/Analyst/Administrator (import JSON).
2. [ ] Gateway JWT validation (JWKS); PEP in `libs/authz`; role×tool matrix tests.
3. [ ] `AUTH_MODE=dev` hardcoded profile.

## Implementation status (2026-11-09)
Implemented in `libs/authz/identity.py`. `AUTH_MODE=keycloak` validates each bearer JWT against
the realm JWKS (fetched once and cached with TTL, refreshed once on key-rotation failure),
verifies the issuer, and maps **realm roles + client roles** (`resource_access[client]`) onto
Viewer / Analyst / Administrator — case-insensitively, with an optional `KEYCLOAK_ROLE_MAP`
override. Audience checking is opt-in (`KEYCLOAK_VERIFY_AUD`, default off, since Keycloak uses
`azp`). The PEP (`libs/authz/policy.py`) enforces `(roles, action, resource)` on every tool and
retrieval, so authorization cannot be bypassed by the model. `AUTH_MODE=dev` remains the offline
default. Role extraction is factored into a pure, unit-tested `extract_roles()`.
