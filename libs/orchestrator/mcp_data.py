"""Dummy enterprise data exposed via the MCP server and the in-process MCP client.
Shared so the real FastMCP server (services/ai-tool-service/server.py) and the agent's
in-process path return identical data. docs/09 §4."""
from __future__ import annotations

ENTERPRISE_DATA: dict[str, list[dict]] = {
    "employees": [
        {"id": "E001", "name": "A. Perera", "dept": "payments", "role": "SRE"},
        {"id": "E002", "name": "R. Silva", "dept": "platform", "role": "Architect"},
        {"id": "E003", "name": "N. Fernando", "dept": "security", "role": "Security Lead"},
    ],
    "services": [
        {"service": "payment-gateway", "owner": "payments", "tier": 1, "on_call": "E001"},
        {"service": "auth", "owner": "platform", "tier": 1, "on_call": "E002"},
        {"service": "ledger", "owner": "payments", "tier": 1, "on_call": "E001"},
    ],
    "incidents": [
        {"id": "INC-2026-0121", "service": "ledger", "root_cause": "db pool exhaustion"},
        {"id": "INC-2026-0304", "service": "payment-gateway", "root_cause": "gateway timeout"},
    ],
}


def lookup(resource: str, query: str = "") -> list[dict]:
    """Return records for a resource, optionally filtered by a substring match on any field."""
    rows = ENTERPRISE_DATA.get(resource, [])
    if not query:
        return rows
    q = query.lower()
    return [r for r in rows if any(q in str(v).lower() for v in r.values())]


def resources() -> list[str]:
    return list(ENTERPRISE_DATA)
