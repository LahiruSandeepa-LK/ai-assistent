"""Tools the orchestrator can call. Every tool passes the PEP first (authorization in code,
not prompt) and is traced in LangSmith. Retrieval-like tools return Chunks so their output flows
through the same grounded-synthesis + citation path. docs/03 §7, docs/06 §4, docs/09 §4."""
from __future__ import annotations

import json

from contracts.models import Chunk, RetrievalRequest, RetrievalResult, Source, UserContext
from authz.policy import enforce_tool
from authz.rbac import max_access_for
from rag.store import get_index
from observability.tracing import traced
from . import mcp_client, mcp_data, tool_web, tool_docparser


@traced(name="tool.knowledge_search", run_type="retriever")
async def knowledge_search(user: UserContext, query: str, *, top_k: int = 6, filters: dict | None = None) -> RetrievalResult:
    enforce_tool(user, "knowledge_search")
    req = RetrievalRequest(query=query, top_k=top_k, filters=filters or {}, rerank=True,
                           access_level_max=max_access_for(user.roles))
    return await get_index().search(req)


@traced(name="tool.web_search", run_type="tool")
async def web_search(user: UserContext, query: str, *, k: int = 3) -> list[Chunk]:
    enforce_tool(user, "web_search")
    return tool_web.search(query, k)


@traced(name="tool.document_parser", run_type="tool")
async def document_parser(user: UserContext, source: str, *, filename: str = "", doc_id: str = "PARSED") -> list[Chunk]:
    enforce_tool(user, "document_parser")
    return tool_docparser.parse(source, filename=filename, doc_id=doc_id)


@traced(name="tool.mcp", run_type="tool")
async def mcp(user: UserContext, resource: str, query: str = "") -> list[Chunk]:
    """Call the MCP server (real over stdio when MCP_SERVER_CMD set; else in-process)."""
    enforce_tool(user, "mcp")
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
