# 17 — Demo script (~45 minutes)

A sequenced walkthrough for presenting the ABC Bank AI Assistant. Times are approximate.

## 0. Setup (before the call)
`docker compose -f docker-compose.yml -f docker-compose.pinecone.yml up --build` and confirm
health (docs/19 §2). Have open: public UI `:8501`, admin UI `:8502`, Keycloak `:8080`, and a
terminal. Offline backup: `make demo` runs the whole pipeline with zero credentials.

## 1. Framing (3 min)
One line: *an enterprise agentic-RAG assistant over organizational knowledge, built to show system
design — observability, security, and production engineering — not just an LLM on a vector DB.*
Show the C4 context diagram (`diagrams/c4-l1-context.drawio`) and the service map
(`docs/13-service-topology.md`).

## 2. Architecture tour (7 min)
- Monorepo: pure-stdlib engine in `libs/`, thin FastAPI/Streamlit services in `services/`.
- The architect ⇄ evaluator design loop and the ADRs (`docs/adr/`) — each major choice justified.
- LangGraph `StateGraph`: supervisor → retrieval/plan → tool/approval → respond, with `Send`
  fan-out (RLM) and `interrupt` HITL. Show `diagrams/langgraph-agent-flow.drawio`.

## 3. Grounded answering, live (6 min)
- Public UI → ask *"What was the root cause of the 2026-01-21 payment outage?"*
- Point out: router → retrieval events streaming in the activity panel, the grounded **cited**
  answer, token usage metered, and — ask the same question again — the **semantic cache** hit.
- Show guardrails: paste a prompt-injection ("ignore your instructions and…") → screened.

## 4. Security & RBAC (6 min)
- Two login models: **SSO → Viewer** (public) and **username/password** (staff). Sign in as
  `analyst`, then `admin`.
- Show the PEP in `libs/authz/policy.py`: authorization is in code, not the prompt. As a Viewer,
  a tool call (web_search/MCP) is denied; as Analyst it's allowed — the model cannot bypass it.
- Keycloak admin console: realm-as-code, roles, the `corporate-sso` broker that maps SSO users to
  Viewer.

## 5. Tools & MCP (5 min)
- Ask *"who owns the payment-gateway service and who's on-call?"* → routes to the **MCP** tool
  (real server over stdio) returning structured records, synthesized + cited.
- Mention web_search (Tavily/offline) and document_parser (pdf/docx/xlsx).

## 6. Admin console (6 min)
- Upload a PDF/Word/Excel → **live indexing progress bar** → then ask about it in public chat
  (shared index). 
- **Runtime LLM config**: create + activate a provider; highlight that the **API key is
  write-only** — never shown or returned (show the `has_secret` flag in the API response).

## 7. Production engineering (5 min)
- True **service-to-service HTTP**: one chat call fans out across containers (show
  `docker compose logs ai-orchestrator`).
- **Redis** (token budget, rate limit, shared cache) and **Postgres** (history, jobs, doc
  registry) — show the tables/keys.
- **Pinecone** local emulator in Docker; **LangSmith** tracing (if keyed) with a shareable run URL.
- Observability: structured JSON logs + correlation IDs.

## 8. Quality & honesty (4 min)
- `make test` → 62 offline / 64 with live backends; `make eval` → Recall@k and citation integrity
  on the golden set.
- The independent validator-agent pass and the fixes it drove.
- Honest limitations: recall is capped by the offline hashing embedder (use OpenAI embeddings +
  Pinecone for production numbers); the SSO broker needs real IdP creds to activate.

## 9. Q&A (3 min)
Have ready: ADR rationale, how to add a new tool/provider (one file + registry), how scaling works
(stateless services + Redis/Postgres/Pinecone shared state).
