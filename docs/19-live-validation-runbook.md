# 19 — Live validation runbook (`docker compose up`)

Step-by-step bring-up and what to verify. The engine + all adapters are unit/integration-tested;
this runbook validates the fully networked stack (Keycloak OAuth, Redis, Postgres, true
service-to-service HTTP, and optionally real Pinecone) on a real Docker host.

## 0. Prerequisites
- Docker Desktop (Mac/Windows) or Docker Engine + compose v2 (Linux).
- `cp .env.example .env` (the committed `.env.example` has no secrets).
- Linux only: add `127.0.0.1 host.docker.internal` to `/etc/hosts` for the browser SSO redirect.

## 1. Bring up the stack
```bash
docker compose up --build
# with real Pinecone (local emulator, no account):
docker compose -f docker-compose.yml -f docker-compose.pinecone.yml up --build
```
Wait for `keycloak` to log "Imported realm abc-bank" and the services to report healthy.

## 2. Verify infrastructure
```bash
docker compose ps                 # all services Up
curl localhost:8000/api/health    # {"status":"ok"}
curl localhost:8800/health        # admin service
docker compose exec redis redis-cli ping            # PONG
docker compose exec postgres psql -U app -d app -c '\dt'   # conversation_turns, ingest_jobs, documents...
```

## 3. Verify Keycloak + the two login models
- Open Keycloak admin at `http://localhost:8080` (admin / admin) → realm **abc-bank** → confirm
  clients `ai-assistant-web`, `ai-assistant-admin`, roles Viewer/Analyst/Administrator, and users
  `admin`, `analyst`.
- **Staff password login:** get a real token and call chat:
  ```bash
  TOKEN=$(curl -s -X POST \
    http://host.docker.internal:8080/realms/abc-bank/protocol/openid-connect/token \
    -d grant_type=password -d client_id=ai-assistant-admin \
    -d username=analyst -d password='Analyst#12345' | jq -r .access_token)
  curl -s -X POST localhost:8000/api/chat -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"message":"what caused the payment outage?"}' | jq '{route, answer}'
  ```
  Expect a grounded, cited answer (401 would mean the issuer/JWKS is misconfigured).
- **Public SSO → Viewer:** fill the `corporate-sso` IdP's `REPLACE_WITH_*` config (realm file or
  admin console) with a real OIDC client, then open `http://localhost:8501` → **Continue with
  SSO**. After the IdP round-trip the user is Viewer (read-only). Confirm the token's
  `realm_access.roles` contains `Viewer`.

## 4. Verify true service-to-service HTTP
A single chat call fans out across containers. Confirm in the logs:
```bash
docker compose logs ai-orchestrator | grep -E "search|complete|call"   # outbound HTTP to leaves
docker compose logs ai-model-gateway                                    # /complete hit
```
`ai-assistant-api` delegates to `ai-orchestrator` (`ORCHESTRATOR_URL`), which calls
`ai-knowledge-retrieval` `/search`, `ai-tool-service` `/call`, and `ai-model-gateway` `/complete`.

## 5. Verify admin upload + live indexing + shared retrieval
- Sign in to the admin console `http://localhost:8502` as `admin / Admin#12345`.
- Upload a PDF/Word/Excel/MD file → watch the progress bar (extracting → chunking → indexing →
  done). Confirm `ingest_jobs` has the row and `documents` gets registered:
  ```bash
  docker compose exec postgres psql -U app -d app -c 'select stage,chunks from ingest_jobs;'
  ```
- In the public chat, ask about the uploaded content → it is retrievable (shared via Pinecone, or
  the `kbindex` volume offline).

## 6. Verify runtime LLM config (write-only secret)
- Admin console → **LLM configuration** → create a config with an API key → activate.
- Confirm the secret is never returned:
  ```bash
  curl -s localhost:8800/admin/llm -H "Authorization: Bearer $ADMIN_TOKEN" | jq
  # each config shows has_secret:true, NO api_key/secret field
  ```

## 7. Verify Redis/Postgres state
```bash
docker compose exec redis redis-cli keys 'usage:*'   # token-budget counters
docker compose exec redis redis-cli keys 'rl:*'      # rate-limit windows
docker compose exec postgres psql -U app -d app -c 'select role,count(*) from conversation_turns group by role;'
```

## Troubleshooting
- **401 on chat with a real token** → issuer mismatch. Ensure browser and containers both use
  `http://host.docker.internal:8080` and Keycloak has `KC_HOSTNAME_URL` set to it.
- **SSO button 500** → `corporate-sso` still has `REPLACE_WITH_*` values; fill real IdP creds.
- **Pinecone errors** → confirm `pinecone-local` is healthy and `PINECONE_HOST` resolves; without
  the override the stack uses the in-memory/`kbindex` store.
