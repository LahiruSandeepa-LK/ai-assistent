"""Tests for MCP + web search + document parser tools, routing, and PEP gating."""
import asyncio
import os

import pytest

from contracts.models import UserContext
from contracts.errors import AuthzError
from rag.ingest import ingest_folder
from orchestrator import ops, tools, mcp_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "fixtures", "sample_docs")
analyst = UserContext(user_id="a", roles=["Analyst"], session_id="t")
viewer = UserContext(user_id="v", roles=["Viewer"], session_id="t")


def test_classify_routes_tool_intents():
    assert ops.classify("who owns the payment-gateway service?", {}) == "tool"
    assert ops.classify("search the web for the latest news on X", {}) == "tool"
    assert ops.classify("parse this document and extract text", {}) == "tool"
    assert ops.classify("what caused the outage?", {}) == "retrieval"


def test_pick_tool():
    assert ops.pick_tool("search the web for X")["tool"] == "web_search"
    assert ops.pick_tool("who owns payment-gateway")["tool"] == "mcp"
    assert ops.pick_tool("look up employee E001")["resource"] == "employees"
    assert ops.pick_tool("parse this document")["tool"] == "document_parser"


def test_mcp_inprocess_returns_chunks():
    chunks = asyncio.run(tools.mcp(analyst, "services", query="payment"))
    assert chunks and any("payment-gateway" in c.text for c in chunks)
    assert chunks[0].source.doc_id == "MCP-SERVICES"


def test_web_search_returns_chunks():
    chunks = asyncio.run(tools.web_search(analyst, "latest langgraph release"))
    assert chunks and chunks[0].source.url


def test_document_parser_html_and_md():
    chunks = asyncio.run(tools.document_parser(analyst, "<h1>Title</h1><p>Hello world</p>", filename="x.html"))
    assert chunks and "Hello world" in " ".join(c.text for c in chunks)


def test_pep_denies_unauthorized_tools_for_viewer():
    with pytest.raises(AuthzError):
        asyncio.run(tools.mcp(viewer, "services"))
    with pytest.raises(AuthzError):
        asyncio.run(tools.web_search(viewer, "x"))
    # document_parser is Viewer+ (utility) — allowed
    assert asyncio.run(tools.document_parser(viewer, "# Hi\nok"))


def test_end_to_end_tool_route():
    from orchestrator.graph import run
    ingest_folder(FIX)
    ans = asyncio.run(run(UserContext(user_id="a2", roles=["Analyst"], session_id="te"),
                          "who owns the payment-gateway service?"))
    assert ans.route == "tool"
    assert any(c.doc_id.startswith("MCP") for c in ans.citations)


def test_real_mcp_stdio_roundtrip(monkeypatch):
    pytest.importorskip("mcp")
    monkeypatch.setenv("PYTHONPATH", os.path.join(ROOT, "libs"))
    monkeypatch.setenv("MCP_SERVER_CMD", f"python {os.path.join(ROOT, 'services', 'ai-tool-service', 'server.py')}")
    assert mcp_client.mcp_enabled_real()
    recs = asyncio.run(mcp_client.call_tool("services", {"query": "payment"}))
    assert any(r.get("service") == "payment-gateway" for r in recs)
