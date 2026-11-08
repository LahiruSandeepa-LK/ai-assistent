"""Identity resolution. Dev mode = hardcoded users; prod = Keycloak JWT (OIDC).
docs/06 §4, ADR-005.

Keycloak path verifies the token signature against the realm's JWKS (cached), checks the
issuer, and maps BOTH realm roles (realm_access.roles) and client roles
(resource_access[client].roles) onto the app roles Viewer/Analyst/Administrator. Role names
are matched case-insensitively and are remappable via KEYCLOAK_ROLE_MAP for installs whose
IdP uses different role names.
"""
from __future__ import annotations

import json
import os
import time

from contracts.errors import AuthzError
from contracts.models import UserContext

# Dev-mode hardcoded users (AUTH_MODE=dev). Token == username.
DEV_USERS: dict[str, list[str]] = {
    "viewer": ["Viewer"],
    "analyst": ["Analyst"],
    "admin": ["Administrator"],
}

APP_ROLES = ("Viewer", "Analyst", "Administrator")


def resolve_user(token: str, session_id: str = "") -> UserContext:
    """Resolve a bearer token to a UserContext.

    AUTH_MODE=dev       -> token is a username in DEV_USERS.
    AUTH_MODE=keycloak  -> validate the OIDC JWT and map roles.
    """
    mode = os.getenv("AUTH_MODE", "dev").lower()
    if mode == "keycloak":
        return _resolve_keycloak(token, session_id)
    roles = DEV_USERS.get(token.strip().lower())
    if not roles:
        raise AuthzError("unknown dev user; use viewer|analyst|admin", token=token)
    return UserContext(user_id=token.strip().lower(), roles=roles, session_id=session_id)


# ---- Keycloak / OIDC ----

def _role_map() -> dict[str, str]:
    """Optional override: KEYCLOAK_ROLE_MAP='idp_role:AppRole,other:AppRole' (case-insensitive)."""
    raw = os.getenv("KEYCLOAK_ROLE_MAP", "")
    out: dict[str, str] = {}
    for pair in raw.split(","):
        if ":" in pair:
            k, v = pair.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def extract_roles(claims: dict, client_id: str | None = None) -> list[str]:
    """Collect app roles from realm_access and resource_access[client]. Pure + unit-tested."""
    raw: list[str] = list(claims.get("realm_access", {}).get("roles", []) or [])
    resource = claims.get("resource_access", {}) or {}
    if client_id and client_id in resource:
        raw += list(resource[client_id].get("roles", []) or [])
    else:
        for entry in resource.values():
            raw += list(entry.get("roles", []) or [])

    overrides = _role_map()
    by_lower = {r.lower(): r for r in APP_ROLES}
    found: list[str] = []
    for r in raw:
        low = r.strip().lower()
        mapped = overrides.get(low) or by_lower.get(low)
        if mapped and mapped not in found:
            found.append(mapped)
    return found


# JWKS cache: {url: (fetched_at, jwks)}; TTL avoids a network round-trip per request.
_JWKS_CACHE: dict[str, tuple[float, dict]] = {}
_JWKS_TTL = int(os.getenv("KEYCLOAK_JWKS_TTL", "3600"))


def _get_jwks(jwks_url: str, force: bool = False) -> dict:  # pragma: no cover - network
    import httpx  # type: ignore

    hit = _JWKS_CACHE.get(jwks_url)
    if hit and not force and (time.time() - hit[0]) < _JWKS_TTL:
        return hit[1]
    jwks = httpx.get(jwks_url, timeout=5).json()
    _JWKS_CACHE[jwks_url] = (time.time(), jwks)
    return jwks


def _resolve_keycloak(token: str, session_id: str) -> UserContext:  # pragma: no cover - needs IdP
    try:
        from jose import jwt  # type: ignore
        from jose.exceptions import JWTError  # type: ignore
        import httpx  # noqa: F401  (import-time check that deps exist)
    except Exception as e:
        raise AuthzError("keycloak mode requires python-jose + httpx") from e

    base = os.environ["KEYCLOAK_URL"].rstrip("/")
    realm = os.environ["KEYCLOAK_REALM"]
    issuer = f"{base}/realms/{realm}"
    jwks_url = f"{issuer}/protocol/openid-connect/certs"
    client_id = os.getenv("KEYCLOAK_CLIENT_ID")
    # Keycloak commonly puts the client in `azp`, not `aud`; verify audience only if asked.
    verify_aud = os.getenv("KEYCLOAK_VERIFY_AUD", "false").lower() == "true"

    def _decode(jwks: dict) -> dict:
        return jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=client_id if verify_aud else None,
            issuer=issuer,
            options={"verify_aud": verify_aud},
        )

    try:
        claims = _decode(_get_jwks(jwks_url))
    except JWTError:
        # Key rotation: refresh JWKS once and retry before giving up.
        try:
            claims = _decode(_get_jwks(jwks_url, force=True))
        except JWTError as e:
            raise AuthzError("invalid or expired token") from e

    roles = extract_roles(claims, client_id)
    if not roles:
        raise AuthzError("token carries no recognised application role")
    user_id = claims.get("preferred_username") or claims.get("sub", "unknown")
    return UserContext(user_id=user_id, roles=roles, session_id=session_id)
