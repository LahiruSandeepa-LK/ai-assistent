"""LangSmith tracing helpers. No-op unless LANGSMITH_TRACING=true + LANGSMITH_API_KEY are set,
so the system runs offline unchanged. docs/07-observability.md, ADR-001.

When enabled, LangGraph auto-traces node transitions to LangSmith; `@traced` additionally wraps
tools/retrieval, and `current_run_url()` returns the shareable run link for the demo (D4).
"""
from __future__ import annotations

import functools
import os


def tracing_enabled() -> bool:
    return bool(os.getenv("LANGSMITH_API_KEY")) and os.getenv("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes")


def configure() -> None:
    """Align the env flags LangChain/LangGraph/langsmith read with our gate.

    When enabled (key + flag), turn auto-tracing on. When NOT enabled, actively force the flags
    OFF — otherwise a stray `LANGSMITH_TRACING=true` (e.g. from .env) with no/invalid API key makes
    the langsmith uploader 401-spam on every run. docs/07."""
    if tracing_enabled():
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGSMITH_PROJECT", "ai-assistant"))
    else:
        for flag in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"):
            if os.environ.get(flag, "").lower() in ("1", "true", "yes"):
                os.environ[flag] = "false"


def traced(name: str | None = None, run_type: str = "tool"):
    """Decorator: wrap a function as a LangSmith span when tracing is on, else passthrough."""
    def deco(fn):
        if not tracing_enabled():
            return fn
        try:
            from langsmith import traceable  # type: ignore

            return traceable(name=name or fn.__name__, run_type=run_type)(fn)
        except Exception:
            return fn
    return deco


def current_run_url() -> str:
    if not tracing_enabled():
        return ""
    try:
        from langsmith.run_helpers import get_current_run_tree  # type: ignore

        rt = get_current_run_tree()
        return rt.get_url() if rt else ""
    except Exception:
        return ""
