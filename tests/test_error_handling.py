"""Inference-path resilience: upstream/LLM/tool failures degrade gracefully, never 500."""
import asyncio

import pytest

from contracts.errors import UpstreamError, ToolTimeoutError
from contracts.models import UserContext

DEAD = "http://127.0.0.1:59999"   # nothing listens here -> fast connection refused


def test_remote_search_maps_transport_error_to_upstream(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_URL", DEAD)
    monkeypatch.setenv("SERVICE_HTTP_TIMEOUT", "2")
    from clients.services import remote_search
    with pytest.raises((UpstreamError, ToolTimeoutError)):
        asyncio.run(remote_search("q", 3, {}, "internal"))


def test_knowledge_search_degrades_to_in_process_when_service_down(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_URL", DEAD)
    monkeypatch.setenv("SERVICE_HTTP_TIMEOUT", "2")
    from rag.ingest import ingest_text
    from rag.store import get_index
    ingest_text(get_index(),
                "---\ndoc_id: EH-1\ntitle: T\naccess_level: public\n---\n\n# S\nwire transfer limit 50000",
                doc_id_fallback="EH-1")
    from orchestrator import tools
    u = UserContext(user_id="a", roles=["Analyst"], session_id="eh")
    res = asyncio.run(tools.knowledge_search(u, "wire transfer limit"))  # must NOT raise
    assert res is not None
    assert any(c.source.doc_id == "EH-1" for c in res.chunks)


def test_gateway_degrades_to_local_when_model_gateway_unreachable(monkeypatch):
    monkeypatch.setenv("MODEL_GATEWAY_URL", DEAD)
    monkeypatch.setenv("SERVICE_HTTP_TIMEOUT", "2")
    from llm.gateway import ModelGateway
    from llm.provider import MockProvider
    gw = ModelGateway(provider=MockProvider())
    c = gw._complete("TASK: synthesize", "QUESTION: x\n\nCONTEXT:\n[D1 | s] body", model="strong")
    assert c.text and c.text.strip()  # fell back to local mock, no exception


def test_run_tool_returns_empty_on_tool_failure(monkeypatch):
    from orchestrator import ops, tools

    async def boom(*a, **k):
        raise RuntimeError("tool down")

    monkeypatch.setattr(tools, "web_search", boom)
    u = UserContext(user_id="a", roles=["Analyst"], session_id="eh")
    out = asyncio.run(ops.run_tool(u, "search the web for X"))
    assert out == []   # degraded, not raised


def test_end_to_end_chat_never_raises_on_upstream_failure(monkeypatch):
    # with all service URLs dead, a full run() must still return an Answer (degraded), not raise
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_URL", DEAD)
    monkeypatch.setenv("MODEL_GATEWAY_URL", DEAD)
    monkeypatch.setenv("TOOL_SERVICE_URL", DEAD)
    monkeypatch.setenv("SERVICE_HTTP_TIMEOUT", "2")
    from orchestrator.graph import run
    u = UserContext(user_id="a", roles=["Analyst"], session_id="eh2")
    ans = asyncio.run(run(u, "what are the home loan rates?"))
    assert ans is not None and ans.text  # graceful degraded answer, no exception
