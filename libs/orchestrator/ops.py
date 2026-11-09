"""Shared node operations used by BOTH the real LangGraph build (graph_langgraph.py) and the
dependency-free fallback runner (graph.py). Keeping the steps here means the two backends
behave identically. docs/03-agent-architecture.md."""
from __future__ import annotations

import re
from typing import Callable, Optional

from contracts.models import AgentEvent, Answer, Citation, Chunk, UserContext
from llm.gateway import get_gateway
from memory.conversation import get_conversation_store
from . import prompts, tools, guardrails

Emit = Optional[Callable[[AgentEvent], None]]

RESEARCH_HINTS = ("summarize all", "recurring", "across", "last year", "over the",
                  "all outage", "root causes", "trend")
CONTEXT_HINTS = ("what did i", "earlier", "previous", "you said", "that answer", "repeat")
WEB_HINTS = ("search the web", "web search", "on the web", "latest news", "look online",
             "search online", "google ", "current price", "today's", "latest version")
MCP_HINTS = ("who owns", "service owner", "on-call", "on call", "oncall", "employee directory",
             "look up employee", "service catalog", "org chart", "directory", "who is on")
DOC_HINTS = ("parse this", "parse the document", "extract text", "read this pdf", "parse pdf",
             "parse document", "parse the pdf")


GREETINGS = ("hi", "hello", "hey", "hiya", "good morning", "good afternoon", "good evening",
             "thanks", "thank you", "thankyou", "ok", "okay", "bye", "goodbye")
GREETING_REPLY = ("Hello! I'm ABC Bank's assistant. I can help you with loans, savings and fixed "
                  "deposits, cards, accounts, exchange rates and remittances, and account-opening "
                  "steps. What would you like to know?")


def is_greeting(message: str) -> bool:
    low = message.strip().lower().rstrip("!.")
    return low in GREETINGS or (len(low.split()) <= 3 and any(low.startswith(g) for g in GREETINGS))


def is_tool_intent(message: str) -> bool:
    low = message.lower()
    return any(h in low for group in (WEB_HINTS, MCP_HINTS, DOC_HINTS) for h in group)


def pick_tool(message: str) -> dict:
    low = message.lower()
    if any(h in low for h in WEB_HINTS):
        return {"tool": "web_search"}
    if any(h in low for h in DOC_HINTS):
        return {"tool": "document_parser"}
    if "service" in low or "owns" in low or "on-call" in low or "on call" in low or "oncall" in low:
        resource = "services"
    elif "incident" in low:
        resource = "incidents"
    elif "employee" in low or "who is" in low or "directory" in low or "staff" in low:
        resource = "employees"
    else:
        resource = "services"
    return {"tool": "mcp", "resource": resource}


def emit(cb: Emit, etype, **data):
    if cb:
        cb(AgentEvent(type=etype, data=data))


def classify(message: str, bundle: dict) -> str:
    low = message.lower().strip()
    if len(low.split()) <= 3 and any(g in low for g in ("hi", "hello", "thanks", "thank you")):
        return "context"
    if any(h in low for h in CONTEXT_HINTS) and bundle.get("recent_turns"):
        return "context"
    if is_tool_intent(message):
        return "tool"
    if any(h in low for h in RESEARCH_HINTS):
        return "research"
    return "retrieval"


async def run_tool(user, message: str, cb: Emit = None) -> list:
    """Execute the selected tool through the PEP; return Chunks (empty if unauthorized)."""
    from contracts.errors import AuthzError
    from . import tools
    sel = pick_tool(message)
    emit(cb, "node", node="tool_router", tool=sel["tool"])
    emit(cb, "tool", tool=sel["tool"], **{k: v for k, v in sel.items() if k != "tool"})
    try:
        if sel["tool"] == "web_search":
            return await tools.web_search(user, message)
        if sel["tool"] == "mcp":
            # return the resource's records (don't filter by the whole question); synthesis picks
            return await tools.mcp(user, sel["resource"], query="")
        if sel["tool"] == "document_parser":
            return await tools.document_parser(user, message)
    except AuthzError as e:
        emit(cb, "validation", verdict="unauthorized", tool=sel["tool"], reason=e.message)
        return []
    except Exception as e:  # upstream/tool failure -> degrade to no tool evidence, never 500
        emit(cb, "validation", verdict="tool_error", tool=sel["tool"], reason=str(e))
        return []
    return []


def decompose(message: str) -> list[str]:
    """Simplified RLM plan-as-code: targeted sub-questions. docs/03 §4."""
    subs = [message]
    if "root cause" in message.lower() or "recurring" in message.lower():
        subs.append("payment failure incident root cause")
        subs.append("payment gateway timeout OR expired certificate OR connection pool")
    return subs


def format_context(chunks: list[Chunk]) -> str:
    out = []
    for c in chunks:
        body = c.text.split("\n", 1)[1] if "\n" in c.text else c.text
        body = guardrails.sanitize_retrieved(body).strip()
        out.append(f"[{c.source.doc_id} | {c.source.section}] {body}")
    return "\n".join(out)


def setup_metering(user: UserContext) -> None:
    from memory.usage import get_usage_store
    gw = get_gateway()
    usage = get_usage_store()
    gw.on_usage = lambda uid, pt, ct, model: usage.record(uid or user.user_id, pt + ct)


async def retrieve_single(user: UserContext, message: str, cb: Emit = None) -> list[Chunk]:
    emit(cb, "node", node="retrieval_agent")
    emit(cb, "retrieval", status="searching")
    res = await tools.knowledge_search(user, message, top_k=5)
    return res.chunks


async def subretrieve(user: UserContext, sub_question: str, cb: Emit = None) -> list[Chunk]:
    emit(cb, "retrieval", status="searching", sub_question=sub_question)
    res = await tools.knowledge_search(user, sub_question, top_k=5)
    return res.chunks


def merge_chunks(groups: list[list[Chunk]], limit: int = 5) -> list[Chunk]:
    seen: dict[str, Chunk] = {}
    for g in groups:
        for c in g:
            if c.chunk_id not in seen or c.score > seen[c.chunk_id].score:
                seen[c.chunk_id] = c
    return sorted(seen.values(), key=lambda c: c.score, reverse=True)[:limit]


NO_ANSWER = ("I'm sorry, I don't have that information at the moment. I can help with ABC Bank "
             "loans, deposits and fixed deposits, cards, accounts, exchange rates and remittances, "
             "and account-opening steps — just ask.")


def strip_markers(text: str) -> str:
    """Remove internal [DOC_ID] citation markers and any leaked meta-commentary so the customer
    sees a clean, natural answer."""
    text = re.sub(r"\s*\[[A-Z0-9][A-Z0-9\-]*\]", "", text)
    text = re.sub(r"(?im)^\s*\(?answer grounded[^\n]*\)?\s*$", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


async def synthesize(user: UserContext, message: str, chunks: list[Chunk], cb: Emit = None, route: str = "retrieval") -> Answer:
    gw = get_gateway()
    if not chunks:
        return Answer(text=NO_ANSWER, route=route, degraded=True)
    emit(cb, "node", node="response")
    ctx = format_context(chunks)
    comp = gw.complete(prompts.SYNTHESIZE, f"QUESTION: {message}\n\nCONTEXT:\n{ctx}", model="strong", user_id=user.user_id)
    text = guardrails.redact_secrets(comp.text)

    # validate citations against retrieved context BEFORE stripping the markers
    ok_cite, hallucinated = guardrails.check_citations(text, chunks)
    grounded = guardrails.groundedness(text, chunks)
    emit(cb, "validation", citations_ok=ok_cite, hallucinated=hallucinated, groundedness=round(grounded, 2))

    cited = set(re.findall(r"\[([A-Z0-9\-]+)\]", text)) - set(hallucinated)
    cites = [Citation(c.source.doc_id, c.source.title, c.source.section, c.source.url)
             for c in chunks if c.source.doc_id in cited] \
        or [Citation(c.source.doc_id, c.source.title, c.source.section, c.source.url) for c in chunks[:3]]

    # remove all internal markers/meta for the customer-facing text
    display = strip_markers(text) or NO_ANSWER
    return Answer(text=display, citations=cites, route=route, reasoning=f"grounded={grounded:.2f}", tokens=comp.total_tokens)


async def context_answer(user: UserContext, message: str, bundle: dict, cb: Emit = None) -> Answer:
    """Answer a follow-up using ONLY the prior turns in this session that are relevant to the
    question (memory-as-RAG) — not the whole conversation history."""
    gw = get_gateway()
    turns = get_conversation_store().relevant_turns(user.session_id or "default", message)
    if not turns:
        return Answer(text="Sure — what would you like to know about ABC Bank's products or services?",
                      route="context")
    emit(cb, "memory", retrieved_turns=len(turns))
    hist = "\n".join(f"{r}: {t}" for r, t in turns)
    c = gw.complete(prompts.CONTEXT, f"QUESTION: {message}\n\nRELEVANT CONVERSATION:\n{hist}",
                    model="fast", user_id=user.user_id)
    return Answer(text=strip_markers(guardrails.redact_secrets(c.text)), route="context",
                  tokens=c.total_tokens)


def maybe_summarize(user: UserContext, sid: str) -> None:
    conv = get_conversation_store()
    if conv.due_for_summary(sid):
        older = conv.older_block(sid)
        if older:
            c = get_gateway().complete(prompts.SUMMARIZE, older, model="fast", user_id=user.user_id)
            conv.set_summary(sid, c.text)
