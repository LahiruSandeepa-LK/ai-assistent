"""MCP client for the agent.

Default: in-process adapter over the shared enterprise data (fast, offline, testable).
When MCP_SERVER_CMD is set (e.g. "python services/ai-tool-service/server.py"), it connects to
the REAL MCP server over stdio using the `mcp` SDK and calls its tools over the protocol.
docs/09 §4, ADR-003 (same mock-vs-real pattern as the LLM providers)."""
from __future__ import annotations

import os
import shlex

from . import mcp_data


def mcp_enabled_real() -> bool:
    return bool(os.getenv("MCP_SERVER_CMD"))


async def call_tool(name: str, arguments: dict) -> list[dict]:
    """Call an MCP tool. `name` is the resource (employees|services|incidents)."""
    if mcp_enabled_real():
        try:
            return await _call_real(name, arguments)
        except Exception:
            pass  # fall back to in-process if the server is unavailable
    return mcp_data.lookup(name, arguments.get("query", ""))


async def _call_real(name: str, arguments: dict) -> list[dict]:  # pragma: no cover - needs a live server
    import json

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    cmd = shlex.split(os.environ["MCP_SERVER_CMD"])
    params = StdioServerParameters(command=cmd[0], args=cmd[1:], env=os.environ.copy())
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments or {})
            # Prefer structured content (mcp 2.x); fall back to parsing text content blocks.
            structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
            if isinstance(structured, dict) and "result" in structured:
                structured = structured["result"]
            if isinstance(structured, list):
                return structured
            out: list[dict] = []
            for block in getattr(result, "content", []) or []:
                text = getattr(block, "text", None)
                if text:
                    try:
                        data = json.loads(text)
                        out.extend(data if isinstance(data, list) else [data])
                    except Exception:
                        out.append({"text": text})
            return out
