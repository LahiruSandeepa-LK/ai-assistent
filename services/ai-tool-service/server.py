"""Real MCP server (Model Context Protocol) exposing ABC Bank dummy enterprise data as MCP
tools over stdio. Run standalone or point the agent at it with
  MCP_SERVER_CMD="python services/ai-tool-service/server.py"
Requires the `mcp` SDK and PYTHONPATH including ./libs. docs/09 §4.
"""
from __future__ import annotations

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
except Exception:  # mcp 2.x renamed FastMCP -> MCPServer
    from mcp.server.mcpserver import MCPServer as _Server

from orchestrator import mcp_data

mcp = _Server("abc-bank-enterprise")


@mcp.tool()
def employees(query: str = "") -> list[dict]:
    """Employee directory. Optional substring filter on any field."""
    return mcp_data.lookup("employees", query)


@mcp.tool()
def services(query: str = "") -> list[dict]:
    """Service catalog (owner, tier, on-call). Optional substring filter."""
    return mcp_data.lookup("services", query)


@mcp.tool()
def incidents(query: str = "") -> list[dict]:
    """Incident records. Optional substring filter."""
    return mcp_data.lookup("incidents", query)


if __name__ == "__main__":
    mcp.run()  # stdio transport
