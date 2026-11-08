"""RBAC matrix + tool/namespace permissions. See docs/06-security-guardrails.md §4."""
from __future__ import annotations

# capability -> minimum roles allowed
TOOL_PERMISSIONS: dict[str, set[str]] = {
    "knowledge_search": {"Viewer", "Analyst", "Administrator"},
    "document_parser": {"Viewer", "Analyst", "Administrator"},
    "python_analysis": {"Analyst", "Administrator"},
    "mcp": {"Analyst", "Administrator"},
    "web_search": {"Analyst", "Administrator"},
    "admin_console": {"Administrator"},
    "document_management": {"Administrator"},
}

# access_level ordering for retrieval clearance
ACCESS_ORDER = ["public", "internal", "confidential", "restricted"]

# max access_level a role may retrieve
ROLE_MAX_ACCESS: dict[str, str] = {
    "Viewer": "internal",
    "Analyst": "confidential",
    "Administrator": "restricted",
}


def can_use_tool(roles: list[str], tool: str) -> bool:
    allowed = TOOL_PERMISSIONS.get(tool, set())
    return any(r in allowed for r in roles)


def max_access_for(roles: list[str]) -> str:
    best = "public"
    for r in roles:
        lvl = ROLE_MAX_ACCESS.get(r, "public")
        if ACCESS_ORDER.index(lvl) > ACCESS_ORDER.index(best):
            best = lvl
    return best


def access_allowed(role_max: str, doc_level: str) -> bool:
    try:
        return ACCESS_ORDER.index(doc_level) <= ACCESS_ORDER.index(role_max)
    except ValueError:
        return False
