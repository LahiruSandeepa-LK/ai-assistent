"""Tools the orchestrator can call. Every tool passes the PEP first (authorization in code,
not prompt) and is traced in LangSmith. Retrieval-like tools return Chunks so their output flows
through the same grounded-synthesis + citation path. docs/03 §7, docs/06 §4, docs/09 §4."""
from __future__ import annotations

import json
import os

from contracts.models import Chunk, RetrievalRequest, RetrievalResult, Source, UserContext
from authz.policy import enforce_tool
from authz.rbac import max_access_for
from rag.store import get_index
from observability.tracing import traced
from . import mcp_client, mcp_data, tool_web, tool_docparser


def _remote(env: str) -> bool:
    return bool(os.getenv(env))


def _degraded(service: str, exc: Exception) -> None:
    import sys

    print(f"[tools] {service} unavailable ({exc!r}); using in-process fallback",
          file=sys.stderr, flush=True)


@traced(name="tool.knowledge_search", run_type="retriever")
async def knowledge_search(user: UserContext, query: str, *, top_k: int = 6, filters: dict | None = None) -> RetrievalResult:
    enforce_tool(user, "knowledge_search")
    access = max_access_for(user.roles)
    if _remote("KNOWLEDGE_RETRIEVAL_URL"):
        from clients.services import remote_search

        try:
            return await remote_search(query, top_k, filters or {}, access)
        except Exception as e:
            _degraded("knowledge-retrieval", e)  # fall through to the in-process index
    req = RetrievalRequest(query=query, top_k=top_k, filters=filters or {}, rerank=True,
                           access_level_max=access)
    try:
        return await get_index().search(req)
    except Exception as e:
        _degraded("in-process index", e)
        return RetrievalResult(chunks=[], degraded=True, note="retrieval unavailable")


@traced(name="tool.web_search", run_type="tool")
async def web_search(user: UserContext, query: str, *, k: int = 3) -> list[Chunk]:
    enforce_tool(user, "web_search")
    if _remote("TOOL_SERVICE_URL"):
        from clients.services import chunk_from_json, remote_tool_call

        try:
            data = await remote_tool_call(user, "web_search", {"query": query})
            return [chunk_from_json(x) for x in data.get("chunks", [])]
        except Exception as e:
            _degraded("ai-tool-service", e)  # fall through to in-process web search
    return tool_web.search(query, k)


@traced(name="tool.document_parser", run_type="tool")
async def document_parser(user: UserContext, source: str, *, filename: str = "", doc_id: str = "PARSED") -> list[Chunk]:
    enforce_tool(user, "document_parser")
    if _remote("TOOL_SERVICE_URL"):
        from clients.services import chunk_from_json, remote_tool_call

        try:
            data = await remote_tool_call(user, "document_parser", {"content": source, "filename": filename})
            return [chunk_from_json(x) for x in data.get("chunks", [])]
        except Exception as e:
            _degraded("ai-tool-service", e)  # fall through to in-process parser
    return tool_docparser.parse(source, filename=filename, doc_id=doc_id)


@traced(name="tool.mcp", run_type="tool")
async def mcp(user: UserContext, resource: str, query: str = "") -> list[Chunk]:
    """Call the MCP server (real over stdio when MCP_SERVER_CMD set; else in-process)."""
    enforce_tool(user, "mcp")
    records: list = []
    if _remote("TOOL_SERVICE_URL"):
        from clients.services import remote_tool_call

        try:
            data = await remote_tool_call(user, "mcp", {"resource": resource, "query": query})
            records = data.get("records", [])
        except Exception as e:
            _degraded("ai-tool-service", e)
            try:
                records = await mcp_client.call_tool(resource, {"query": query})
            except Exception:
                records = []
    else:
        records = await mcp_client.call_tool(resource, {"query": query})
    chunks: list[Chunk] = []
    for i, rec in enumerate(records):
        text = json.dumps(rec)
        chunks.append(Chunk(chunk_id=f"mcp-{resource}-{i}", text=f"{resource}: {text}",
                            source=Source(doc_id=f"MCP-{resource.upper()}", title=f"MCP {resource}", section=resource),
                            score=1.0 - i * 0.05))
    return chunks


def python_analysis(user: UserContext, numbers: list[float]) -> dict:
    """Sandboxed structured analysis (no eval of model text). Analyst+ only."""
    enforce_tool(user, "python_analysis")
    if not numbers:
        return {"count": 0}
    n = len(numbers)
    total = sum(numbers)
    return {"count": n, "sum": total, "mean": total / n, "min": min(numbers), "max": max(numbers)}


# raw-record helper for the REST /call endpoint (ai-tool-service)
def mcp_records(user: UserContext, resource: str, query: str = "") -> list[dict]:
    enforce_tool(user, "mcp")
    return mcp_data.lookup(resource, query)
