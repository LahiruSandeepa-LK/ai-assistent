"""Tests for the real LangGraph backend (StateGraph structure, HITL interrupt, parity)."""
import asyncio
import os

import pytest

pytest.importorskip("langgraph")

from contracts.models import UserContext
from rag.ingest import ingest_folder
from orchestrator.graph import backend_name

FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "sample_docs")


@pytest.fixture(scope="module", autouse=True)
def _ingest():
    ingest_folder(FIX)


def test_backend_is_langgraph():
    assert backend_name() == "langgraph"


def test_compiled_graph_structure():
    from orchestrator.graph_langgraph import compiled
    nodes = set(compiled().get_graph().nodes)
    for n in ("supervisor", "retrieval", "plan", "subretrieve", "aggregate", "approval", "respond", "context"):
        assert n in nodes, f"missing node {n}"


def test_hitl_interrupt_fires_only_when_flagged(monkeypatch):
    from orchestrator import graph_langgraph as glg
    calls = []
    monkeypatch.setattr(glg, "interrupt", lambda payload: calls.append(payload))
    asyncio.run(glg.n_approval({"requires_approval": True}, {"configurable": {}}))
    assert calls, "interrupt should fire for a high-risk step"
    calls.clear()
    asyncio.run(glg.n_approval({}, {"configurable": {}}))
    assert not calls, "interrupt must not fire for normal steps"


def test_langgraph_answer_is_grounded_and_cited():
    from orchestrator.graph import run
    user = UserContext(user_id="lg", roles=["Analyst"], session_id="lg1")
    ans = asyncio.run(run(user, "What was the root cause of the 2026-01-21 payment outage?"))
    assert ans.route in ("retrieval", "research")
    assert any(c.doc_id == "INC-2026-0121" for c in ans.citations)
