"""ai-model-gateway — single entry for LLM calls: routing + fallback + token metering. ADR-010."""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from llm.gateway import get_gateway
from memory.usage import get_usage_store

app = FastAPI(title="ai-model-gateway")
_gw = get_gateway()
_gw.on_usage = lambda uid, pt, ct, model: get_usage_store().record(uid, pt + ct)


class CompleteBody(BaseModel):
    system: str
    user: str
    model: str = "strong"
    user_id: str = ""


@app.get("/health")
async def health():
    return {"status": "ok", "provider": _gw.provider.name}


@app.post("/complete")
async def complete(body: CompleteBody):
    c = _gw.complete(body.system, body.user, model=body.model, user_id=body.user_id)
    return {"text": c.text, "prompt_tokens": c.prompt_tokens,
            "completion_tokens": c.completion_tokens, "total_tokens": c.total_tokens,
            "provider": c.provider, "timed_out": c.timed_out}
