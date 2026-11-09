# 18 — Requirements → code map

Where each assessment requirement is implemented, for reviewers. Paths are repo-relative.

| Requirement | Implementation | Tests |
|-------------|----------------|-------|
| Agentic patterns (not just LLM+vector DB) | `libs/orchestrator/graph_langgraph.py` (StateGraph: supervisor, retrieval, plan/`Send` fan-out, aggregate, tool, approval/`interrupt`, respond); `graph.py` fallback | `tests/test_langgraph.py` |
| RLM decomposition | `ops.decompose` + `Send` fan-out → `subretrieve` → aggregate | `test_langgraph.py` |
| Hybrid retrieval | `libs/rag/hybrid.py` (RRF + rerank), `bm25.py`, `embeddings.py`, `store.py` | `test_unit.py` |
| Section-aware chunking + metadata | `libs/rag/chunking.py` (metadata header per chunk) | `test_unit.py` |
| Vector DB (Pinecone) | `libs/rag/vectorstore_pinecone.py` (+ local emulator via `PINECONE_HOST`); `docker-compose.pinecone.yml` | `test_backends.py` |
| Embeddings | `libs/rag/embeddings.py` + `embeddings_openai.py` | `test_backends.py` |
| Orchestration (LangGraph) | `graph_langgraph.py`; backend select in `graph.py` | `test_langgraph.py` |
| Observability (LangSmith) | `libs/observability/tracing.py` (traced spans, run URL), `logging.py` (JSON + correlation id) | — |
| Tools / MCP | real MCP server `services/ai-tool-service/server.py`; client `libs/orchestrator/mcp_client.py`; `tools.py`, `tool_web.py`, `tool_docparser.py` | `test_tools.py` |
| RBAC (3 roles) + no-bypass | `libs/authz/rbac.py` (matrix), `policy.py` (PEP enforced on every tool/retrieval) | `test_tools.py`, `test_unit.py` |
| Guardrails | `libs/orchestrator/guardrails.py` (injection screen, citation integrity, secret redaction) | `test_unit.py`, `test_end_to_end.py` |
| AuthN — Keycloak, two login models | realm `infra/keycloak/abc-bank-realm.json`; validation `libs/authz/identity.py`; token acquisition `libs/authclient/keycloak_client.py` (SSO+PKCE, password grant) | `test_authclient.py`, `test_backends.py` |
| Public SSO → Viewer | realm IdP broker + `oidc-hardcoded-role-idp-mapper`; UI `services/ui-public/app.py` | — (needs live IdP) |
| Token budget + rate limiting | `libs/memory/usage.py` (Redis `INCRBY`), API rate limiter `services/ai-assistant-api/app/main.py` (Redis fixed-window) | `test_integration_backends.py` |
| Memory (history, summary, cache) | `libs/memory/conversation.py` (+ Redis cache), `db/stores.py` (Postgres history) | `test_integration_backends.py` |
| Admin: document upload + progress | `libs/admin/jobs.py`, `ingest_runner.py`; `services/ai-admin-service/app/main.py` (`/admin/documents/upload`, `/admin/jobs/{id}`); UI `services/ui-admin/app.py` | `test_admin_jobs.py`, `test_admin_api.py` |
| Admin: LLM config, write-only secret | `libs/llm/config_store.py` (create-only, secret never serialised); endpoints in admin service | `test_llm_config.py`, `test_admin_api.py` |
| Real state — Redis | `libs/memory/redis_client.py`, `usage.py`, `conversation.py` | `test_integration_backends.py` |
| Real state — Postgres | `libs/db/engine.py`, `stores.py` | `test_integration_backends.py` |
| Microservices + Docker | `docker-compose.yml` (10 services + Redis/Postgres/Keycloak), per-service Dockerfiles | — |
| True service-to-service HTTP | `libs/clients/services.py`; seams in `tools.py`, `gateway.py`, API edge | end-to-end verified (docs/19 §4) |
| Model gateway + metering | `libs/llm/gateway.py`, `services/ai-model-gateway` | `test_unit.py` |
| Evaluation harness | `services/ai-admin-service/eval/run_eval.py`, `fixtures/golden.jsonl` | `make eval` |
| ADRs / design docs | `docs/00`–`19`, `docs/adr/ADR-001`–`011` | — |

**Run order for a reviewer:** `make install` → `make test` (62/64) → `make eval` → `make demo`
(offline) → `docker compose up` for the full stack (see `docs/19-live-validation-runbook.md`).
