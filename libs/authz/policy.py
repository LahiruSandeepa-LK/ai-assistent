"""Policy Enforcement Point (PEP). The agent CANNOT bypass this — it runs in code
using the gateway-signed identity, not the model's decision. docs/06 §4 (S6/S7)."""
from __future__ import annotations

from contracts.errors import AuthzError
from contracts.models import UserContext
from authz.rbac import can_use_tool


def enforce_tool(user: UserContext, tool: str) -> None:
    """Raise AuthzError if the user's roles may not use the tool."""
    if not can_use_tool(user.roles, tool):
        raise AuthzError(
            f"role(s) {user.roles} may not use tool '{tool}'",
            tool=tool,
            user_id=user.user_id,
        )


def check_tool(user: UserContext, tool: str) -> bool:
    return can_use_tool(user.roles, tool)
