"""ai-assistant-api — public chat edge.

authN/RBAC -> rate-limit -> TOKEN-BUDGET gate -> input guardrail -> orchestrator (SSE/JSON).
Runs the orchestrator in-process for the POC (shares `libs`); set ORCHESTRATOR_URL to call
the ai-orchestrator service over HTTP instead. docs/09 §1, docs/13, docs/14.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from contracts.errors import AppError
from contracts.models import AgentEvent, UserContext, to_jsonable
from authz.identity import resolve_user
from authz.rbac import can_use_tool
from memory.usage import get_usage_store
from observability.logging import get_logger, new_correlation_id, set_context, log
from orchestrator.graph import run as run_graph

app = FastAPI(title="ai-assistant-api")
logger = get_logger("ai-assistant-api")

_FRIENDLY_ERROR = ("I'm having trouble answering right now. Please try again in a moment — if it "
                   "keeps happening, contact an ABC Bank branch for help.")

# ---- simple in-memory token-bucket rate limit (per user) ----
_RATE = {"Viewer": 20, "Analyst": 60, "Administrator": 120}  # per minute
_buckets: dict[str, tuple[float, float]] = {}  # user -> (tokens, last_ts)


def _rate_ok(user: UserContext) -> bool:
    cap = _RATE.get(user.top_role, 20)
    # Redis fixed-window counter (shared across replicas) when available.
    try:
        from memory.redis_client import get_redis

        r = get_redis()
        if r is not None:
            window = int(time.time() // 60)
            key = f"rl:{user.user_id}:{window}"
            n = r.incr(key)
            if n == 1:
                r.expire(key, 60)
            return n <= cap
    except Exception:
        pass
    # in-memory token bucket fallback
    refill = cap / 60.0
    tokens, last = _buckets.get(user.user_id, (cap, time.time()))
    now = time.time()
    tokens = min(cap, tokens + (now - last) * refill)
    if tokens < 1:
        _buckets[user.user_id] = (tokens, now)
        return False
    _buckets[user.user_id] = (tokens - 1, now)
    return True


class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str
    stream: bool = False


def _auth(authorization: str | None, session_id: str) -> UserContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token (dev: 'Bearer viewer|analyst|admin')")
    token = authorization.split(" ", 1)[1]
    try:
        return resolve_user(token, session_id=session_id)
    except AppError as e:
        raise HTTPException(e.http_status, e.message)


@app.on_event("startup")
async def _startup_ingest():
    # In offline (no-Pinecone) mode the index is in-process, so the API (which runs the
    # orchestrator in-process) ingests the corpus on startup. With Pinecone set, this is a no-op
    # you can skip (data is already shared). Controlled by SAMPLE_DOCS + INGEST_ON_START.
    path = os.getenv("SAMPLE_DOCS", "")
    if os.getenv("INGEST_ON_START", "false").lower() in ("1", "true", "yes") and path and os.path.isdir(path):
        from rag.ingest import ingest_folder
        stats = ingest_folder(path)
        log(logger, "startup_ingest", documents=len(stats), chunks=sum(stats.values()))


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/me")
async def me(authorization: str | None = Header(default=None)):
    user = _auth(authorization, "default")
    return {"user_id": user.user_id, "roles": user.roles}


@app.get("/api/history")
async def history(session_id: str = "", authorization: str | None = Header(default=None)):
    """The signed-in user's previous sessions (read-only, for the UI history panel). This is NOT
    fed to the agent — new sessions start fresh. Excludes the current session_id."""
    user = _auth(authorization, "default")
    from memory.conversation import get_conversation_store, HISTORY_SESSIONS

    try:
        sessions = get_conversation_store().list_user_sessions(
            user.user_id, limit=HISTORY_SESSIONS, exclude_session=session_id)
    except Exception as e:
        log(logger, "history_error", error=str(e))
        sessions = []
    return {"sessions": sessions}


@app.post("/api/chat")
async def chat(req: ChatRequest, authorization: str | None = Header(default=None)):
    cid = new_correlation_id()
    user = _auth(authorization, req.session_id)
    set_context(correlation_id=cid, session_id=req.session_id, user_id=user.user_id)

    if not can_use_tool(user.roles, "knowledge_search"):
        raise HTTPException(403, "role not permitted to chat")
    if not _rate_ok(user):
        raise HTTPException(429, "rate limit exceeded; slow down")

    # token-budget pre-check (hard stop)
    usage = get_usage_store().check(user.user_id, user.top_role)
    if usage.remaining <= 0:
        return JSONResponse(
            status_code=402,
            content={
                "answer": f"You've reached your token limit for this period. It resets {usage.reset_at}.",
                "route": "token_limit",
                "usage": to_jsonable(usage),
            },
        )

    log(logger, "chat_request", route="start", message_len=len(req.message))

    if req.stream:
        return StreamingResponse(_stream(user, req.message, cid), media_type="text/event-stream")

    # Any inference failure (upstream service down/slow, LLM error) degrades to a friendly answer
    # instead of a 500. The orchestrator also guards itself; this is defence in depth at the edge.
    try:
        # True service-to-service: delegate to the ai-orchestrator service over HTTP when
        # configured; otherwise run the orchestrator in-process (offline/POC).
        if os.getenv("ORCHESTRATOR_URL"):
            from clients.services import remote_agent_run

            data = await remote_agent_run(user, req.message)
        else:
            events: list[dict] = []
            ans = await run_graph(user, req.message, emit=lambda e: events.append(e.to_dict()))
            data = {"answer": ans.text, "route": ans.route,
                    "citations": [to_jsonable(c) for c in ans.citations], "events": events}
    except Exception as e:
        log(logger, "chat_error", error=str(e), error_type=type(e).__name__)
        data = {"answer": _FRIENDLY_ERROR, "route": "error", "citations": [], "events": []}

    data["usage"] = to_jsonable(get_usage_store().get(user.user_id, user.top_role))
    data["correlation_id"] = cid
    return data


async def _stream(user: UserContext, message: str, cid: str):
    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def emit(e: AgentEvent):
        loop.call_soon_threadsafe(q.put_nowait, e.to_dict())

    task = asyncio.create_task(run_graph(user, message, emit=emit))
    yield f"event: meta\ndata: {json.dumps({'correlation_id': cid})}\n\n"
    while not task.done() or not q.empty():
        try:
            item = await asyncio.wait_for(q.get(), timeout=0.1)
            yield f"event: {item['type']}\ndata: {json.dumps(item)}\n\n"
        except asyncio.TimeoutError:
            continue
    # surface a graceful done event even if the run raised, instead of breaking the SSE stream
    try:
        ans = task.result()
        payload = {"answer": ans.text, "route": ans.route}
    except Exception as e:
        log(logger, "chat_error", error=str(e), error_type=type(e).__name__)
        payload = {"answer": _FRIENDLY_ERROR, "route": "error"}
    yield f"event: done\ndata: {json.dumps(payload)}\n\n"
