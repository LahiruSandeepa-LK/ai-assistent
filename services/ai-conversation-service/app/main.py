"""ai-conversation-service — history, memory, semantic cache, token-budget state. docs/13, docs/14."""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from memory.conversation import get_conversation_store
from memory.usage import get_usage_store

app = FastAPI(title="ai-conversation-service")


class UsageCheck(BaseModel):
    user_id: str
    role: str = "Viewer"


class UsageRecord(BaseModel):
    user_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/context/{session_id}")
async def context(session_id: str):
    return get_conversation_store().context_bundle(session_id)


@app.post("/usage/check")
async def usage_check(body: UsageCheck):
    u = get_usage_store().check(body.user_id, body.role)
    return {"user_id": u.user_id, "limit": u.limit, "used": u.used,
            "remaining": u.remaining, "reset_at": u.reset_at}


@app.post("/usage/record")
async def usage_record(body: UsageRecord):
    get_usage_store().record(body.user_id, body.prompt_tokens + body.completion_tokens)
    return {"ok": True}
