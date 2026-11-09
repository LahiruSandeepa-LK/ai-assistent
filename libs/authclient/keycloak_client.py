"""Client-side Keycloak/OIDC helpers used by the two UIs to OBTAIN tokens (the API side only
VALIDATES them — see libs/authz/identity.py).

Two login models, per the product spec:
  * Public users  -> SSO via identity brokering. `sso_login_url()` sends them straight to the
    corporate IdP through Keycloak (kc_idp_hint); first-login maps them to the Viewer role
    (realm default role). `exchange_code()` completes the Authorization-Code (+PKCE) flow.
  * Admin/Analyst -> username/password. `password_login()` uses the OIDC Resource-Owner Password
    grant against the admin client (direct access grants enabled on that client).

All endpoints are derived from KEYCLOAK_URL + KEYCLOAK_REALM. docs/06, ADR-005.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import urllib.parse

import httpx


def _base() -> tuple[str, str]:
    url = os.getenv("KEYCLOAK_URL", "http://localhost:8080").rstrip("/")
    realm = os.getenv("KEYCLOAK_REALM", "abc-bank")
    return url, realm


def issuer() -> str:
    url, realm = _base()
    return f"{url}/realms/{realm}"


def _endpoint(suffix: str) -> str:
    return f"{issuer()}/protocol/openid-connect/{suffix}"


# ---- PKCE helpers (public SSO client) ----

def new_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for an Authorization-Code + PKCE flow."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def sso_login_url(redirect_uri: str, *, code_challenge: str, state: str = "",
                  client_id: str | None = None, idp_hint: str | None = None) -> str:
    """Build the Keycloak authorization URL. `idp_hint` (default $KEYCLOAK_SSO_IDP) jumps straight
    to the brokered corporate IdP so the public user never sees the Keycloak login form."""
    cid = client_id or os.getenv("KEYCLOAK_WEB_CLIENT_ID", "ai-assistant-web")
    hint = idp_hint if idp_hint is not None else os.getenv("KEYCLOAK_SSO_IDP", "corporate-sso")
    params = {
        "client_id": cid,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": redirect_uri,
        "state": state or secrets.token_urlsafe(16),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if hint:
        params["kc_idp_hint"] = hint
    return _endpoint("auth") + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str, redirect_uri: str, code_verifier: str,
                  *, client_id: str | None = None, timeout: float = 10.0) -> dict:
    """Complete the Authorization-Code flow -> token response {access_token, ...}."""
    cid = client_id or os.getenv("KEYCLOAK_WEB_CLIENT_ID", "ai-assistant-web")
    data = {
        "grant_type": "authorization_code",
        "client_id": cid,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    r = httpx.post(_endpoint("token"), data=data, timeout=timeout)
    r.raise_for_status()
    return r.json()


def password_login(username: str, password: str, *, client_id: str | None = None,
                   client_secret: str | None = None, timeout: float = 10.0) -> dict:
    """Resource-Owner Password grant for staff (admin/analyst) -> token response."""
    cid = client_id or os.getenv("KEYCLOAK_ADMIN_CLIENT_ID", "ai-assistant-admin")
    data = {
        "grant_type": "password",
        "client_id": cid,
        "username": username,
        "password": password,
        "scope": "openid profile email",
    }
    sec = client_secret if client_secret is not None else os.getenv("KEYCLOAK_ADMIN_CLIENT_SECRET", "")
    if sec:
        data["client_secret"] = sec
    r = httpx.post(_endpoint("token"), data=data, timeout=timeout)
    r.raise_for_status()
    return r.json()
