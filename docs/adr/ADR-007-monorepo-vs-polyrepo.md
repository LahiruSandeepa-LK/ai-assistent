# ADR-007: Monorepo with multiple containerized services

**Status:** Accepted · **Date:** 2026-11-08 · **Deciders:** AI Lead, Platform

## Context
The brief asks for a microservice architecture in a single repository, multiple services run
with Docker. We must choose how to structure the code and share contracts across services.

## Decision
A **monorepo** containing all services under `services/` and shared internal packages under
`libs/` (contracts, authz, observability, llm). Each service has its own Dockerfile; Docker
Compose runs them together.

## Options Considered
### Option A: Monorepo + microservices (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium |
| Cross-service change cost | Low (atomic) |
| CI | Single pipeline |
| Team familiarity | Good for a small team |

**Pros:** atomic cross-service commits; one source of truth for shared contracts/RBAC/logging;
one CI; easy local run; matches the brief. **Cons:** careful module boundaries needed to avoid
accidental coupling.

### Option B: Polyrepo (one repo per service)
**Pros:** hard service isolation; independent release cadence. **Cons:** versioning tax on shared
contracts; multi-repo PRs for one change; heavier for a small team and a POC.

## Trade-off Analysis
For a small team on a time-boxed POC, the monorepo's atomic-change and single-CI benefits
outweigh the discipline cost. Services remain independently deployable (separate Dockerfiles), so
we keep microservice benefits without the polyrepo overhead.

## Consequences
- Easier: shared contracts, refactors, local orchestration.
- Harder: enforcing boundaries (mitigated by `libs/` + import rules + lint).
- Revisit: split hot services into their own repos if team/scale grows.

## Action Items
1. [ ] `libs/` shared packages installed into each service.
2. [ ] Per-service Dockerfiles; one CI with path-filtered jobs.
3. [ ] Lint rule preventing service→service imports (only via `libs/` + HTTP).
