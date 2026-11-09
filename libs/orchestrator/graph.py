"""Orchestrator entry point (ai-orchestrator brain).

`run()` is the public API. It handles memory, input guardrail, semantic cache, and token
metering, then dispatches the core flow to either:
  • the REAL LangGraph StateGraph (graph_langgraph.py) when `langgraph` is installed, or
  • a dependency-free fallback pipeline (identical steps via ops.py) otherwise.
Set USE_LANGGRAPH=off to force the fallback. docs/03-agent-architecture.md.
"""
from __future__ import annotations

import os
from typing import Optional

from contracts.models import AgentEvent, Answer, Citation, UserContext
from memory.conversation import get_conversation_store
from . import ops, guardrails

Emit = Optional[callable]


def use_langgraph() -> bool:
    if os.getenv("USE_LANGGRAPH", "auto").lower() in ("off", "0", "false"):
        return False
    try:
        import langgraph  # noqa: F401
        return True
    except Exception:
        return False


def backend_name() -> str:
    return "langgraph" if use_langgraph() else "pipeline"


async def _pipeline_core(user: UserContext, message: str, emit: Emit) -> Answer:
    """Dependency-free equivalent of the LangGraph flow (same ops)."""
    conv = get_conversation_store()
    bundle = conv.context_bundle(user.session_id or "default")
    route = ops.classify(message, bundle)
    ops.emit(emit, "node", node="supervisor", route=route)
    if route == "context":
        return await ops.context_answer(user, message, bundle, emit)
    if route == "tool":
        chunks = await ops.run_tool(user, message, emit)
        return await ops.synthesize(user, message, chunks, emit, route="tool")
    if route == "research":
        ops.emit(emit, "node", node="research_agent_rlm", plan="map_reduce")
        groups = [await ops.subretrieve(user, s, emit) for s in ops.decompose(message)]
        chunks = ops.merge_chunks(groups)
        ops.emit(emit, "node", node="aggregate", merged=len(chunks))
    else:
        chunks = await ops.retrieve_single(user, message, emit)
    return await ops.synthesize(user, message, chunks, emit, route=route)


async def run(user: UserContext, message: str, emit: Emit = None) -> Answer:
    ops.setup_metering(user)
    conv = get_conversation_store()
    sid = user.session_id or "default"
    conv.add_user(sid, message, user.user_id)

    # input guardrail
    ok, reason = guardrails.screen_input(message)
    if not ok:
        ops.emit(emit, "validation", verdict="blocked", reason=reason)
        ans = Answer(text="I can't help with that request.", route="blocked")
        conv.add_assistant(sid, ans.text, user.user_id)
        ops.emit(emit, "final", answer=ans.text, route=ans.route)
        return ans

    # greeting / pleasantry: friendly welcome, no retrieval or LLM, no history dump
    if ops.is_greeting(message):
        ans = Answer(text=ops.GREETING_REPLY, route="greeting")
        conv.add_assistant(sid, ans.text, user.user_id)
        ops.emit(emit, "final", answer=ans.text, route="greeting")
        return ans

    # topical scope rail: reject out-of-domain (non-banking) questions BEFORE the LLM/retrieval.
    # In-session follow-ups ("what did you say earlier?") reference prior turns, so they bypass it.
    low = message.lower()
    bundle = conv.context_bundle(sid)
    is_followup = any(h in low for h in ops.CONTEXT_HINTS) and bool(bundle.get("recent_turns"))
    if not is_followup:
        in_scope, _why = guardrails.in_scope(message)
        if not in_scope:
            ops.emit(emit, "validation", verdict="out_of_scope", reason="off-domain question")
            ans = Answer(text=ops.OUT_OF_SCOPE_REPLY, route="out_of_scope")
            conv.add_assistant(sid, ans.text, user.user_id)
            ops.emit(emit, "final", answer=ans.text, route="out_of_scope")
            return ans

    # router: semantic cache
    ops.emit(emit, "node", node="router")
    cached = conv.cache_lookup(sid, message)
    if cached:
        text, cites = cached
        ops.emit(emit, "node", node="cache", hit=True)
        # cache stores citations as plain dicts (JSON-safe); rebuild Citation objects
        cites = [Citation(**c) if isinstance(c, dict) else c for c in (cites or [])]
        ans = Answer(text=text, citations=cites, route="cache")
        conv.add_assistant(sid, ans.text, user.user_id)
        ops.emit(emit, "final", answer=ans.text, route="cache")
        return ans

    backend = backend_name()
    if backend == "langgraph":
        from .graph_langgraph import run_langgraph
        ans = await run_langgraph(user, message, emit)
    else:
        ans = await _pipeline_core(user, message, emit)

    conv.add_assistant(sid, ans.text, user.user_id)
    if ans.route not in ("blocked", "context"):
        conv.cache_store(sid, message, ans.text, ans.citations)
    ops.maybe_summarize(user, sid)
    ops.emit(emit, "final", answer=ans.text, route=ans.route,
             citations=[c.doc_id for c in ans.citations], backend=backend)
    return ans
