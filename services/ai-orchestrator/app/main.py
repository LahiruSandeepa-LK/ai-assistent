"""ai-orchestrator — the LangGraph brain exposed as a service. docs/03, docs/09 §2."""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from contracts.models import UserContext, to_jsonable
from orchestrator.graph import run as run_graph

app = FastAPI(title="ai-orchestrator")


class RunRequest(BaseModel):
    user_id: str
    roles: list[str]
    session_id: str = "default"
    message: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/agent/run")
async def agent_run(req: RunRequest):
    user = UserContext(user_id=req.user_id, roles=req.roles, session_id=req.session_id)
    events: list[dict] = []
    ans = await run_graph(user, req.message, emit=lambda e: events.append(e.to_dict()))
    return {"answer": ans.text, "route": ans.route,
            "citations": [to_jsonable(c) for c in ans.citations], "events": events}
