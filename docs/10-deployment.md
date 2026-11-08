# 10 — Deployment (Docker Compose)

> Covers containerized deployment (bonus B6) and deliverable D1 (public repo runnable locally).
> Everything runs with `docker compose up`. See `diagrams/deployment-docker-compose.drawio`.

## 1. Topology

```
                              docker network: ai-assistant-net
 ┌────────────┐ :8501                                    ┌──────────┐ :8100  ┌───────────┐
 │ ui-public  │──────┐                             ┌────▶│  agent   │───────▶│ retrieval │──▶ Pinecone
 │ Streamlit  │◀──SSE│                       chat  │     │ LangGraph│        └───────────┘    embeddings
 └────────────┘      │   :8000  ┌──────────┐───────┘     └──┬────┬──┘             (cloud)      (cloud)
                     ├─────────▶│ gateway  │                │    │ MCP
 ┌────────────┐ :8502│         │ FastAPI  │  admin  ┌──────┘    ▼                 LangSmith (cloud)
 │ ui-admin   │──────┘         │ /api +   │─────────▶│ ingest  ┌──────┐           LLM provider (cloud)
 │ Streamlit  │   (Admin only) │ /admin   │  /ingest │ :8400   │ mcp  │
 └────────────┘                └────┬─────┘          └────┬────┘└──────┘
                                    │ OIDC                │ upsert ▲
                                    ▼                     ▼        │
                              ┌──────────┐          ┌───────────┐  │ Pinecone
                              │ keycloak │          │ Pinecone  │◀─┘ (cloud)
                              └────┬─────┘          └───────────┘
                    ┌──────────────┴─┐    ┌──────────────┐
                    │   postgres     │    │    redis     │
                    │(authz, memory, │    │(checkpointer,│
                    │ feedback, audit│    │ cache, rate  │
                    │ doc registry)  │    │ buckets)     │
                    └────────────────┘    └──────────────┘

 batch job:  ingest CLI ──▶ Pinecone (initial mock corpus)   [profiles: ["tools"]]
```

## 2. `docker-compose.yml` (service list)

| Service | Image/build | Ports | Depends on | Notes |
|---------|-------------|-------|-----------|-------|
| `ui-public` | build `services/ui-public` | 8501 | gateway | Interface 1 — public assistant (Streamlit) |
| `ui-admin` | build `services/ui-admin` | 8502 | gateway | Interface 2 — admin console (Streamlit), Administrator-only |
| `gateway` | build `services/gateway` | 8000 | keycloak, redis, agent, ingest | public + admin edges |
| `agent` | build `services/agent` | 8100 (internal) | retrieval, redis, postgres, mcp | LangGraph |
| `retrieval` | build `services/retrieval` | 8200 (internal) | — | Pinecone client |
| `ingest` | build `services/ingestion` | 8400 (internal) | postgres | document-mgmt API + batch CLI (`profiles: ["tools"]` for batch) |
| `mcp` | build `services/mcp` | 8300 (internal) | — | dummy data |
| `keycloak` | `quay.io/keycloak/keycloak` | 8080 | postgres | realm import on start |
| `redis` | `redis:7` | 6379 (internal) | — | checkpointer+cache+buckets |
| `postgres` | `postgres:16` | 5432 (internal) | — | app + keycloak DBs, document registry |

Healthchecks on every long-running service; `depends_on: condition: service_healthy` so
startup order is correct. Secrets via `.env` (never committed); `.env.example` documents all keys.

## 3. Configuration (12-factor)

Key env vars (full list in `.env.example`):
```
LLM_PROVIDER=anthropic           ANTHROPIC_API_KEY=...     OPENAI_API_KEY=...(fallback)
EMBEDDING_PROVIDER=...            EMBEDDING_API_KEY=...
PINECONE_API_KEY=...             PINECONE_INDEX=ai-assistant
LANGSMITH_API_KEY=...            LANGSMITH_PROJECT=ai-assistant-dev   LANGSMITH_TRACING=true
KEYCLOAK_URL=...  KEYCLOAK_REALM=ai-assistant  KEYCLOAK_CLIENT_ID=...  KEYCLOAK_CLIENT_SECRET=...
REDIS_URL=redis://redis:6379/0
POSTGRES_DSN=postgresql+asyncpg://...@postgres:5432/app
RATE_LIMIT_VIEWER=20  RATE_LIMIT_ANALYST=60  RATE_LIMIT_ADMIN=120   # per minute, configurable
MAX_DEPTH=2  MAX_RETRIES=2  NODE_BUDGET=40
AUTH_MODE=keycloak   # or "dev" for hardcoded users
```

## 4. Dev vs prod

- `docker-compose.dev.yml` override: `AUTH_MODE=dev` (hardcoded Viewer/Analyst/Admin users so
  the graph runs without Keycloak), volume mounts for hot reload, verbose logging.
- `make dev` → dev stack; `make up` → full stack with Keycloak; `make ingest` → run the
  ingestion job; `make test` → unit+integration+guardrail tests.

## 5. Scaling notes

- `ui-public`, `ui-admin`, `gateway`, `agent`, `retrieval`, `ingest` are stateless → e.g.
  `docker compose up --scale agent=3` (or K8s later). State is in Redis/Postgres/Pinecone. The
  two UIs scale and deploy independently, so the admin console can even be kept on an
  internal-only network in production.
- Kubernetes is the production target (HPA on the agent, separate node pools); Compose is the
  POC deployment the brief asks for. The Dockerfiles and 12-factor config make that migration
  straightforward.

## 6. Git history (deliverable D1)

The brief requires a **public repo with maintained commit history**. Recommended convention:
Conventional Commits, one logical change per commit, meaningful messages that tell the build
story (scaffold → retrieval → graph → RLM → security → observability → compose → tests). This
design package is committed first as the blueprint.
