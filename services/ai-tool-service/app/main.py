"""ai-tool-service — tool registry + execution (authz checked in code). Exposes the agent tools
over REST; the real MCP server is server.py (stdio). docs/03 §7, docs/09 §4."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from contracts.errors import AuthzError
from contracts.models import UserContext, to_jsonable
from authz.rbac import TOOL_PERMISSIONS
from orchestrator import tools

app = FastAPI(title="ai-tool-service")


class ToolCall(BaseModel):
    user_id: str
    roles: list[str]
    tool: str
    args: dict = {}


@app.get("/health")
async def health():
    return {"status": "ok", "tools": list(TOOL_PERMISSIONS)}


@app.post("/call")
async def call(body: ToolCall):
    user = UserContext(user_id=body.user_id, roles=body.roles)
    a = body.args
    try:
        if body.tool == "knowledge_search":
            return to_jsonable(await tools.knowledge_search(user, a.get("query", ""), top_k=a.get("top_k", 6)))
        if body.tool == "web_search":
            return {"chunks": [to_jsonable(c) for c in await tools.web_search(user, a.get("query", ""))]}
        if body.tool == "document_parser":
            return {"chunks": [to_jsonable(c) for c in await tools.document_parser(user, a.get("content", ""), filename=a.get("filename", ""))]}
        if body.tool == "mcp":
            return {"records": tools.mcp_records(user, a.get("resource", "services"), a.get("query", ""))}
        if body.tool == "python_analysis":
            return tools.python_analysis(user, a.get("numbers", []))
        raise HTTPException(404, f"unknown tool {body.tool}")
    except AuthzError as e:
        raise HTTPException(403, e.message)
