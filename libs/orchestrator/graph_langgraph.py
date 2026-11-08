"""Real LangGraph StateGraph for ai-orchestrator.

Uses: StateGraph + MemorySaver checkpointer, conditional edges (router), `Send` fan-out for the
RLM research step, and an `interrupt()` HITL node (inert unless a step is flagged high-risk).
Node transitions auto-trace to LangSmith when tracing is enabled (observability/tracing.py).
Memory, cache, token pre-check and input guardrail live in graph.run() (the wrapper); this graph
covers supervisor -> {retrieval | research(RLM) | context} -> approval -> respond.
docs/03-agent-architecture.md, ADR-001.
"""
from __future__ import annotations

import operator
import os
import uuid
from typing import Annotated, Optional, TypedDict

from langgraph.graph import START, END, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Send, interrupt

from contracts.models import Answer, Citation, UserContext
from memory.conversation import get_conversation_store
from rag.store import get_index
from observability.tracing import configure, current_run_url
from . import ops


class GState(TypedDict, total=False):
    message: str
    route: str
    plan: list[str]
    chunk_ids: list[str]
    subchunk_ids: Annotated[list[str], operator.add]
    sub_question: str
    requires_approval: bool
    answer_text: str
    answer_route: str
    citations: list[str]


def _cfg(config):
    return (config or {}).get("configurable", {})


def _emit(config, etype, **data):
    ops.emit(_cfg(config).get("emit"), etype, **data)


def _user(config) -> UserContext:
    return _cfg(config)["user"]


async def n_supervisor(state: GState, config) -> dict:
    user = _user(config)
    bundle = get_conversation_store().context_bundle(user.session_id or "default")
    route = ops.classify(state["message"], bundle)
    _emit(config, "node", node="supervisor", route=route)
    return {"route": route}


async def n_retrieval(state: GState, config) -> dict:
    chunks = await ops.retrieve_single(_user(config), state["message"], _cfg(config).get("emit"))
    return {"chunk_ids": [c.chunk_id for c in chunks]}


async def n_plan(state: GState, config) -> dict:
    _emit(config, "node", node="research_agent_rlm", plan="map_reduce")
    return {"plan": ops.decompose(state["message"])}


def fan_out(state: GState):
    """Conditional edge: Send one sub-agent per RLM batch (dynamic fan-out)."""
    return [Send("subretrieve", {"message": state["message"], "sub_question": s}) for s in state["plan"]]


async def n_subretrieve(state: GState, config) -> dict:
    chunks = await ops.subretrieve(_user(config), state["sub_question"], _cfg(config).get("emit"))
    return {"subchunk_ids": [c.chunk_id for c in chunks]}


async def n_aggregate(state: GState, config) -> dict:
    idx = get_index()
    merged = ops.merge_chunks([[idx.chunks[c] for c in state.get("subchunk_ids", []) if c in idx.chunks]])
    _emit(config, "node", node="aggregate", merged=len(merged))
    return {"chunk_ids": [c.chunk_id for c in merged]}


async def n_tool(state: GState, config) -> dict:
    # Tool outputs (web/MCP/parsed) aren't in the vector index, so synthesize here and finish.
    user = _user(config)
    cb = _cfg(config).get("emit")
    chunks = await ops.run_tool(user, state["message"], cb)
    ans = await ops.synthesize(user, state["message"], chunks, cb, route="tool")
    return {"answer_text": ans.text, "answer_route": "tool", "citations": [c.doc_id for c in ans.citations]}


async def n_context(state: GState, config) -> dict:
    user = _user(config)
    bundle = get_conversation_store().context_bundle(user.session_id or "default")
    ans = await ops.context_answer(user, state["message"], bundle, _cfg(config).get("emit"))
    return {"answer_text": ans.text, "answer_route": "context", "citations": [c.doc_id for c in ans.citations]}


async def n_approval(state: GState, config) -> dict:
    # Human-in-the-loop: pause for approval on high-risk actions (inert unless flagged).
    if state.get("requires_approval"):
        _emit(config, "node", node="hitl_approval", status="interrupt")
        interrupt({"reason": "high-risk action requires human approval"})
    return {}


async def n_respond(state: GState, config) -> dict:
    user = _user(config)
    idx = get_index()
    chunks = [idx.chunks[c] for c in state.get("chunk_ids", []) if c in idx.chunks]
    ans = await ops.synthesize(user, state["message"], chunks, _cfg(config).get("emit"), route=state.get("route", "retrieval"))
    return {"answer_text": ans.text, "answer_route": ans.route, "citations": [c.doc_id for c in ans.citations]}


def route_after_supervisor(state: GState) -> str:
    return {"retrieval": "retrieval", "research": "plan", "context": "context", "tool": "tool"}.get(state["route"], "retrieval")


def _build():
    g = StateGraph(GState)
    g.add_node("supervisor", n_supervisor)
    g.add_node("retrieval", n_retrieval)
    g.add_node("plan", n_plan)
    g.add_node("subretrieve", n_subretrieve)
    g.add_node("aggregate", n_aggregate)
    g.add_node("context", n_context)
    g.add_node("tool", n_tool)
    g.add_node("approval", n_approval)
    g.add_node("respond", n_respond)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", route_after_supervisor,
                            {"retrieval": "retrieval", "plan": "plan", "context": "context", "tool": "tool"})
    g.add_conditional_edges("plan", fan_out, ["subretrieve"])
    g.add_edge("subretrieve", "aggregate")
    g.add_edge("aggregate", "approval")
    g.add_edge("retrieval", "approval")
    g.add_edge("approval", "respond")
    g.add_edge("context", END)
    g.add_edge("tool", END)
    g.add_edge("respond", END)
    return g.compile(checkpointer=MemorySaver())


_COMPILED = None


def compiled():
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = _build()
    return _COMPILED


async def run_langgraph(user: UserContext, message: str, emit=None) -> Answer:
    configure()  # enable LangSmith auto-tracing of node transitions if configured
    sid = user.session_id or "default"
    cfg = {"configurable": {"thread_id": f"{sid}-{uuid.uuid4().hex[:8]}", "emit": emit, "user": user}}
    final = await compiled().ainvoke({"message": message}, cfg)

    url = current_run_url()
    if url:
        ops.emit(emit, "trace", langsmith_url=url)

    idx = get_index()
    def _cite(doc_id: str) -> Citation:
        for c in idx.chunks.values():
            if c.source.doc_id == doc_id:
                return Citation(doc_id, c.source.title, c.source.section, c.source.url)
        return Citation(doc_id)

    route = final.get("answer_route", final.get("route", "retrieval"))
    return Answer(
        text=final.get("answer_text", ""),
        citations=[_cite(d) for d in final.get("citations", [])],
        route=route,
    )
