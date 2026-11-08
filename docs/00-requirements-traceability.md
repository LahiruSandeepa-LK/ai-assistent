# 00 — Requirements Traceability Matrix

This document is the contract between the assignment and the design. Every requirement in
the brief is extracted, given an ID, mapped to the part of the design that satisfies it, and
linked to the evidence the POC must produce. The **Evaluator pass** (`12-evaluation-validation.md`)
scores the design against this matrix.

Legend — Coverage: ✅ fully designed · 🟡 designed, simplified for POC · ⭘ optional/bonus.

---

## 1. Functional requirements

| ID | Requirement (from brief) | Design location | Coverage |
|----|--------------------------|-----------------|----------|
| F1 | Search across organizational documents | `04-rag-retrieval.md` Hybrid search | ✅ |
| F2 | Answer questions conversationally | `03-agent-architecture.md` Response agent | ✅ |
| F3 | Explain reasoning | `03` reasoning trace + `07` LangSmith + UI activity panel | ✅ |
| F4 | Retrieve supporting evidence (citations) | `04` document attribution + `06` hallucinated-citation guardrail | ✅ |
| F5 | Maintain conversation context | `05-memory.md` short-term memory | ✅ |
| F6 | Invoke external tools when required | `03` tool-calling + `09` MCP service | ✅ |
| F7 | Multiple user roles with controlled access | `06` RBAC (Viewer/Analyst/Administrator) | ✅ |

## 2. Technical requirements

### 2.1 Frontend (Streamlit) — **two interfaces**

The system ships **two separate Streamlit front ends** (ADR-009): the **Public Assistant** chat
UI (requirements FE1–FE11 below, for all authenticated users) and the **Admin Console**
(requirements AD1–AD6 in §2.1b, Administrators only). The public chat never exposes
document-management or admin tools.

| ID | Requirement | Design location | Coverage |
|----|-------------|-----------------|----------|
| FE1 | Lightweight Streamlit chat interface (Public Assistant) | `01` ui-public, `09` streaming contract | ✅ |
| FE2 | Multi-turn conversations | `05` memory + session state | ✅ |
| FE3 | Streaming responses | `09` SSE/token streaming | ✅ |
| FE4 | Agent Activity Panel: current agent state | `07` state events → UI | ✅ |
| FE5 | Active LangGraph node (Deep agents) | `03` node events emitted on transition | ✅ |
| FE6 | Tool calls being executed | `07` tool-call events | ✅ |
| FE7 | Retrieval status | `04` retrieval events | ✅ |
| FE8 | Memory updates | `05` memory-write events | ✅ |
| FE9 | Validation results | `03` validation node events | ✅ |
| FE10 | Final response generation | `03` response node streaming | ✅ |
| FE11 | Evaluator can observe internal behavior | `07` + activity panel + LangSmith link | ✅ |

### 2.1b Admin Console (Administrator-only interface)

The second interface added per the requirement for "an admin interface to update documents".

| ID | Requirement | Design location | Coverage |
|----|-------------|-----------------|----------|
| AD1 | Separate admin interface, Administrator-only | `01` ui-admin, `06` RBAC, ADR-009 | ✅ |
| AD2 | Upload / update / delete organizational documents | `09` Admin API, `01` doc-management flow | ✅ |
| AD3 | Trigger (re)indexing into the vector store | `09` `/admin/documents` → ingestion service, `04` | ✅ |
| AD4 | Browse knowledge base (docs, namespaces, metadata) | `09` Admin API, `04` | ✅ |
| AD5 | Review answer-quality feedback + audit log | `07` feedback, `06` audit | ✅ |
| AD6 | Observability shortcuts (LangSmith run links) | `07` | ✅ |

### 2.2 Backend

| ID | Requirement | Design location | Coverage |
|----|-------------|-----------------|----------|
| BE1 | Python + FastAPI | `08` stack, `09` API | ✅ |
| BE2 | Async programming patterns | `09` async handlers, `01` async flow | ✅ |
| BE3 | Async APIs | `09` all endpoints `async def` | ✅ |
| BE4 | Async retrieval | `04` `asyncio.gather` dense+sparse | ✅ |
| BE5 | Async tool execution | `03` async tool nodes, `09` MCP async client | ✅ |
| BE6 | Proper exception handling | `06`/`11` error taxonomy + graceful degradation | ✅ |
| BE7 | Structured logging | `07` JSON logs + correlation IDs | ✅ |

### 2.3 AI architecture

| ID | Requirement | Design location | Coverage |
|----|-------------|-----------------|----------|
| AI1 | LangGraph as orchestration engine | `03`, ADR-001 | ✅ |
| AI2 | Multiple specialized agents | `03` Supervisor/Retrieval/Research/Response/Validation | ✅ |
| AI3 | Supervisor: intent, decomposition, routing | `03` Supervisor node | ✅ |
| AI4 | Retrieval agent: RAG + vector search | `03`+`04` | ✅ |
| AI5 | Research agent: deep investigation, recursion | `03` RLM research subgraph | ✅ |
| AI6 | Response agent: final answer generation | `03` Response node | ✅ |

### 2.4 Recursive Language Model (RLM)

| ID | Requirement | Design location | Coverage |
|----|-------------|-----------------|----------|
| RLM1 | Avoid loading entire docs into context | `03` RLM targeted-section retrieval | ✅ |
| RLM2 | Explore document collections | `03` collection scan via metadata | ✅ |
| RLM3 | Generate Python-based search plans | `03` plan-as-code node (sandboxed) | ✅ |
| RLM4 | Decompose large tasks | `03` Supervisor + Research decomposition | ✅ |
| RLM5 | Retrieve targeted sections | `04` section-level chunks | ✅ |
| RLM6 | Call sub-agents recursively | `03` `Send` fan-out + depth guard | ✅ |
| RLM7 | Aggregate results | `03` reduce/aggregate node | ✅ |
| RLM8 | Worked example: outage/payment-failure summary | `03` §RLM walkthrough | ✅ |

### 2.5 Retrieval

| ID | Requirement | Design location | Coverage |
|----|-------------|-----------------|----------|
| R1 | Hybrid search | `04` | ✅ |
| R2 | Dense search (embeddings) | `04` dense path | ✅ |
| R3 | Sparse search (BM25/keyword) | `04` sparse path | ✅ |
| R4 | Hybrid ranking (combine scores) | `04` RRF fusion + rerank | ✅ |
| R5 | Vector DB = Pinecone | `04`, ADR-002 | ✅ |
| R6 | Namespaces | `04` namespace strategy | ✅ |
| R7 | Metadata filtering | `04` metadata schema + filters | ✅ |
| R8 | Hybrid retrieval in Pinecone | `04` sparse-dense index | ✅ |
| R9 | Document attribution | `04` citation payload | ✅ |

### 2.6 Memory

| ID | Requirement | Design location | Coverage |
|----|-------------|-----------------|----------|
| M1 | Conversational memory | `05` | ✅ |
| M2 | User context | `05` user profile memory | ✅ |
| M3 | Previous questions | `05` short-term buffer | ✅ |
| M4 | Relevant historical interactions | `05` long-term vector memory | ✅ |
| M5 | Memory survives multiple turns per session | `05` checkpointer (Redis/Postgres) | ✅ |
| M6 | Explain memory design decisions | `05` §rationale, ADR-006 | ✅ |

### 2.7 Tool calling

| ID | Requirement | Design location | Coverage |
|----|-------------|-----------------|----------|
| T1 | Knowledge Search Tool | `03` tools, `04` | ✅ |
| T2 | MCP Tool / server with dummy enterprise data | `09` MCP service | 🟡 (lower priority per brief) |
| T3 | Python Analysis Tool (structured analysis) | `03` sandboxed analysis tool | ✅ |
| T4 | Agent invokes MCP when required | `03` tool router | ✅ |

### 2.8 LLM

| ID | Requirement | Design location | Coverage |
|----|-------------|-----------------|----------|
| L1 | Any modern LLM | ADR-003 | ✅ |
| L2 | Document model-selection rationale | ADR-003, `08` | ✅ |

### 2.9 Observability

| ID | Requirement | Design location | Coverage |
|----|-------------|-----------------|----------|
| O1 | LangSmith mandatory | `07`, ADR-001 | ✅ |
| O2 | Trace every conversation | `07` run tree | ✅ |
| O3 | Trace tool calls | `07` | ✅ |
| O4 | Trace agent transitions | `07` node spans | ✅ |
| O5 | Trace retrieval operations | `07` retrieval spans | ✅ |
| O6 | Evaluator can inspect traces | `07` project + shareable run URLs | ✅ |

### 2.10 Security

| ID | Requirement | Design location | Coverage |
|----|-------------|-----------------|----------|
| S1 | Prompt injection protection (override, exfiltration, tool abuse) | `06` §1 | ✅ |
| S2 | Input validation (requests, tool params, retrieved content) | `06` §2 | ✅ |
| S3 | Guardrails (unsafe tool exec, unauthorized access, hallucinated citations, invalid responses, brand value) | `06` §3 | ✅ |
| S4 | Auth: hardcoded OR Keycloak | `06`+ADR-005 (Keycloak) | ✅ |
| S5 | RBAC: Viewer / Analyst / Administrator | `06` role matrix | ✅ |
| S6 | Tool execution respects role permissions | `06` policy enforcement point | ✅ |
| S7 | Agent cannot bypass authorization | `06` server-side enforcement, not prompt-level | ✅ |
| S8 | Rate limiting: token bucket, per-user, configurable, graceful | `06` §5, ADR-008 | ✅ |

### 2.11 Error handling

| ID | Requirement | Design location | Coverage |
|----|-------------|-----------------|----------|
| E1 | LLM failures | `11` error taxonomy, retries+fallback | ✅ |
| E2 | Vector DB failures | `11` cache + degrade to sparse-only | ✅ |
| E3 | MCP failures | `11` circuit breaker | ✅ |
| E4 | Tool timeouts | `11` async timeout + partial answer | ✅ |
| E5 | Invalid requests | `06` validation 4xx | ✅ |
| E6 | Degrade gracefully | `11` degradation ladder | ✅ |

## 3. Deliverables (brief §Deliverables)

| ID | Deliverable | Where addressed |
|----|-------------|-----------------|
| D1 | Public source-code repository | `10`/`11` repo + git history guidance (design package here) |
| D2 | Architecture diagram | `/diagrams/*.drawio` + `02-c4-model.md` |
| D3 | Demo video (45 min) with LangSmith traces | `11` demo script outline |
| D4 | LangSmith traces in demo | `07` |
| D5 | Assumptions & trade-offs in demo | §5 here + every ADR |

## 4. Bonus points (brief §Bonus)

| ID | Bonus | Design location | Coverage |
|----|-------|-----------------|----------|
| B1 | Multi-agent collaboration (state mgmt + failure/butterfly handling) | `03` §state + §failure | ⭘✅ |
| B2 | Human-in-the-loop approval node | `03` HITL interrupt node | ⭘✅ |
| B3 | Reranking layer | `04` cross-encoder rerank | ⭘✅ |
| B4 | Long-term memory | `05` long-term vector memory | ⭘✅ |
| B5 | Feedback loop for answer quality | `07` feedback → LangSmith datasets | ⭘✅ |
| B6 | Containerized deployment (Docker Compose) | `10` | ⭘✅ |

## 5. Assumptions & trade-offs (consolidated)

1. **Company persona = ABC Bank (fictional).** "ABC Bank" is a made-up example company used
   purely to give the assistant a consistent brand voice for the brand-value guardrail. It is
   **not a real organization**, and the system uses **no sensitive, regulated, or real customer
   data** — all documents are mock/generated. The persona simply raises the bar on brand-safety,
   citation integrity, and refusal behavior, which we lean into (`06`).
2. **Scale target is POC-realistic:** thousands of documents, tens of concurrent users,
   p95 end-to-end latency budget ~6–10 s for multi-hop research answers, ~2–4 s for simple
   lookups. We design for horizontal scalability but do not over-engineer for web scale.
3. **Primary LLM = Anthropic Claude** (reasoning + tool use + prompt-injection robustness),
   **fallback = OpenAI**; embeddings via a dedicated embedding model. Rationale in ADR-003.
   This is swappable behind an `LLMProvider` interface.
4. **Auth = Keycloak (Option B)** over hardcoded users, because RBAC + "agent cannot bypass
   authorization" is graded and Keycloak gives real OIDC tokens and role claims. A hardcoded
   fallback profile exists for `make dev` so the system runs without Keycloak in the loop.
5. **Pinecone** is mandated; we use its native sparse-dense (hybrid) index to satisfy R8
   without running a separate OpenSearch cluster for the POC. Trade-off noted in ADR-004.
6. **MCP tool is explicitly lower priority** in the brief; we design it fully but mark its
   data as dummy/mock and keep it the first thing cut if time is short.
7. **RLM is implemented as a "simplified but conceptually complete" version** as the brief
   permits: real decomposition, real targeted retrieval, real recursion with a depth guard —
   not a research-grade RLM.
8. **Monorepo, multi-service:** one Git repo, multiple independently-containerized services,
   shared internal libraries. Trade-off vs polyrepo in ADR-007.

## 6. Out of scope for the POC

Fine-tuning or training models; production multi-region HA; full data-ingestion pipeline
for real corporate systems (we ship a mock ingestion CLI); SSO federation beyond Keycloak;
a bespoke UI design system (Streamlit defaults are explicitly acceptable per the brief).
