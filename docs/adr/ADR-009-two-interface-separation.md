# ADR-009: Separate public chat and admin interfaces

**Status:** Accepted · **Date:** 2026-11-08 · **Deciders:** AI Lead, Security

## Context
The product needs two audiences with very different needs: everyday users who **chat** with the
assistant, and administrators who **manage the knowledge base** (upload/update/delete documents)
and operate the system (review feedback, audit, observability). Document management is a
high-privilege, state-changing capability and a prime target for abuse, so how we expose it
matters. Persona is **ABC Bank** (a fictional example company; no sensitive/real data).

## Decision
Ship **two separate front-end interfaces** as independent containers:
- **`ui-public`** — the Public Assistant chat window (all authenticated roles).
- **`ui-admin`** — the Admin Console (Administrators only): document management, KB browser,
  feedback/audit review, observability links.

They talk to **different route groups** on the same gateway: `/api/*` (chat) and `/admin/*`
(admin, Administrator-gated). `ui-public` has no code path to `/admin/*`. Document-management
operations go gateway → ingestion service `/ingest`, authorized at the edge **and** the PEP.

## Options Considered
### Option A: Two separate interfaces/containers (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium (one more container) |
| Security | High (separate surface + edge) |
| Deployability | High (admin can be internal-only) |

**Pros:** admin capabilities never ship in the public app's bundle or routes; the admin console
can be placed on an internal-only network in production; clear audience separation; least
privilege by construction. **Cons:** a second Streamlit app + container to build/run.

### Option B: One app with an "admin" tab gated by role
**Pros:** one container. **Cons:** admin code and routes are present in the public surface and
only *hidden* by role — larger attack surface; a client-side gate mistake exposes admin
functions; harder to isolate network-wise.

### Option C: Admin via CLI/scripts only (no UI)
**Pros:** simplest to secure. **Cons:** poor admin UX; the requirement explicitly asks for an
**admin interface** to update documents.

## Trade-off Analysis
One extra container is a small cost for a materially smaller attack surface and cleaner
operational boundaries — important when the privileged capability is modifying the knowledge
base that grounds every answer. Both UIs are thin Streamlit apps over the same gateway, so
duplication is minimal.

## Consequences
- Easier: least-privilege, network isolation of admin, independent scaling/deployment.
- Harder: two UIs to maintain; shared UI helpers extracted to avoid duplication.
- Revisit: SSO-gated admin portal / separate admin domain in production.

## Action Items
1. [ ] `services/ui-public` and `services/ui-admin` (Streamlit).
2. [ ] Gateway `/api/*` (chat) and `/admin/*` (Administrator-only) route groups.
3. [ ] Ingestion service `/ingest` for admin document ops; document registry in Postgres.
4. [ ] authz tests: non-admin blocked from every `/admin/*` route and `/ingest`.
