"""HTTP clients for true service-to-service calls. Each in-process tool/gateway/orchestrator call
delegates here when the matching *_URL env var is set, so the same code runs either in-process
(offline/tests) or across the networked microservices (docker compose). docs/09, docs/13.

Env seams:
  KNOWLEDGE_RETRIEVAL_URL -> ai-knowledge-retrieval /search
  TOOL_SERVICE_URL        -> ai-tool-service /call
  MODEL_GATEWAY_URL       -> ai-model-gateway /complete
  ORCHESTRATOR_URL        -> ai-orchestrator /agent/run
"""
from __future__ import annotations

import os

import httpx

from contracts.models import Chunk, RetrievalResult, Source, UserContext
from llm.provider import Completion

_TIMEOUT = float(os.getenv("SERVICE_HTTP_TIMEOUT", "60"))


def url(env: str) -> str:
    return os.getenv(env, "").rstrip("/")


# ---- deserialisation ----
def chunk_from_json(d: dict) -> Chunk:
    src = d.get("source", {}) or {}
    return Chunk(
        chunk_id=d.get("chunk_id", ""), text=d.get("text", ""),
        source=Source(doc_id=src.get("doc_id", ""), title=src.get("title", ""),
                      section=src.get("section", ""), url=src.get("url", "")),
        metadata=d.get("metadata", {}) or {},
        dense_score=d.get("dense_score", 0.0), sparse_score=d.get("sparse_score", 0.0),
        rerank_score=d.get("rerank_score", 0.0), score=d.get("score", 0.0))


# ---- retrieval ----
async def remote_search(query: str, top_k: int, filters: dict, access_level_max: str) -> RetrievalResult:
    base = url("KNOWLEDGE_RETRIEVAL_URL")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{base}/search", json={"query": query, "top_k": top_k,
                                                 "filters": filters or {}, "rerank": True,
                                                 "access_level_max": access_level_max})
        r.raise_for_status()
        data = r.json()
    return RetrievalResult(chunks=[chunk_from_json(x) for x in data.get("chunks", [])],
                           degraded=data.get("degraded", False), note=data.get("note", ""))


# ---- tools ----
async def remote_tool_call(user: UserContext, tool: str, args: dict) -> dict:
    base = url("TOOL_SERVICE_URL")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{base}/call", json={"user_id": user.user_id, "roles": user.roles,
                                               "tool": tool, "args": args})
        if r.status_code == 403:
            from contracts.errors import AuthzError

            raise AuthzError(f"tool {tool} not permitted")
        r.raise_for_status()
        return r.json()


# ---- model gateway (sync; the gateway path is sync) ----
def remote_complete(system: str, user: str, model: str, user_id: str) -> Completion:
    base = url("MODEL_GATEWAY_URL")
    r = httpx.post(f"{base}/complete", json={"system": system, "user": user, "model": model,
                                             "user_id": user_id}, timeout=_TIMEOUT)
    r.raise_for_status()
    d = r.json()
    return Completion(text=d["text"], prompt_tokens=d.get("prompt_tokens", 0),
                      completion_tokens=d.get("completion_tokens", 0))


# ---- orchestrator ----
async def remote_agent_run(user: UserContext, message: str) -> dict:
    base = url("ORCHESTRATOR_URL")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{base}/agent/run", json={"user_id": user.user_id, "roles": user.roles,
                                                    "session_id": user.session_id, "message": message})
        r.raise_for_status()
        return r.json()
