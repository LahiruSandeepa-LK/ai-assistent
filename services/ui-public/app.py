"""ui-public — Streamlit chat + agent activity panel. docs/00 FE1-FE11.

Login models (per spec):
  * Public users  -> "Continue with SSO" (Keycloak identity brokering; mapped to Viewer).
  * Staff         -> username/password (analyst/admin).
A dev fallback (role buttons) is offered only when AUTH_MODE=dev so the demo runs offline.

    PYTHONPATH=../../libs API_URL=http://localhost:8000 streamlit run app.py
"""
from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8501")
AUTH_MODE = os.getenv("AUTH_MODE", "dev").lower()

st.set_page_config(page_title="ABC Bank Assistant", layout="wide")

# PKCE verifiers pending a redirect, keyed by state. MODULE-level (not session_state): the SSO
# redirect commonly returns in a fresh Streamlit session, so the verifier must live in the server
# process, not the browser session, to survive the round-trip.
_PENDING: dict = {}


def _handle_sso_callback() -> bool:
    """If Keycloak redirected back with ?code=, complete the flow and store the token."""
    params = st.query_params
    code = params.get("code")
    state = params.get("state")
    if not code:
        return False
    try:
        from authclient.keycloak_client import exchange_code

        verifier = _PENDING.pop(state, "")
        tok = exchange_code(code, f"{PUBLIC_BASE_URL}/", verifier)
        st.session_state.token = tok.get("access_token")
        st.session_state.identity = "sso"
        st.query_params.clear()
        return True
    except Exception as e:
        st.error(f"SSO sign-in failed: {e}")
        st.query_params.clear()
        return False


def _login_view():
    st.title("ABC Bank — AI Assistant")
    st.caption("Sign in to ask about policies, incidents and runbooks.")

    st.subheader("Public access")
    try:
        from authclient.keycloak_client import new_pkce, sso_login_url

        verifier, challenge = new_pkce()
        import secrets as _s
        state = _s.token_urlsafe(12)
        _PENDING[state] = verifier
        url = sso_login_url(f"{PUBLIC_BASE_URL}/", code_challenge=challenge, state=state)
        st.link_button("Continue with SSO →", url, use_container_width=True)
        st.caption("Single sign-on via your corporate identity provider. Grants read-only (Viewer) access.")
    except Exception as e:
        st.caption(f"(SSO unavailable: {e})")

    st.divider()
    st.subheader("Staff sign-in")
    with st.form("staff"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in"):
            try:
                from authclient.keycloak_client import password_login

                tok = password_login(u, p)
                st.session_state.token = tok.get("access_token")
                st.session_state.identity = "staff"
                st.rerun()
            except Exception as e:
                if AUTH_MODE == "dev":
                    st.session_state.token = u.strip().lower()
                    st.session_state.identity = "dev"
                    st.rerun()
                else:
                    st.error(f"sign-in failed: {e}")

    if AUTH_MODE == "dev":
        st.divider()
        st.caption("Dev quick sign-in (offline):")
        cols = st.columns(3)
        for i, role in enumerate(["viewer", "analyst", "admin"]):
            if cols[i].button(role, key=f"dev-{role}"):
                st.session_state.token = role
                st.session_state.identity = "dev"
                st.rerun()


# ---- auth gate ----
_handle_sso_callback()
if "token" not in st.session_state:
    _login_view()
    st.stop()

st.title("ABC Bank — AI Assistant")
with st.sidebar:
    st.success(f"Signed in ({st.session_state.get('identity','')})")
    if st.button("Sign out"):
        for k in ("token", "identity"):
            st.session_state.pop(k, None)
        st.rerun()

if "history" not in st.session_state:
    st.session_state.history = []

col_chat, col_activity = st.columns([3, 2])

with col_chat:
    for turn in st.session_state.history:
        st.chat_message(turn["role"]).write(turn["content"])
    prompt = st.chat_input("Ask about policies, incidents, runbooks…")

if prompt:
    st.session_state.history.append({"role": "user", "content": prompt})
    with col_chat:
        st.chat_message("user").write(prompt)
    try:
        r = httpx.post(
            f"{API_URL}/api/chat",
            headers={"Authorization": f"Bearer {st.session_state.token}"},
            json={"session_id": st.session_state.get("sid", "ui-session"), "message": prompt},
            timeout=30,
        )
        data = r.json()
    except Exception as e:
        data = {"answer": f"(API unreachable: {e})", "route": "error", "events": [], "citations": []}

    answer = data.get("answer", "")
    cites = ", ".join(c["doc_id"] for c in data.get("citations", []))
    with col_chat:
        st.chat_message("assistant").write(answer + (f"\n\n*sources: {cites}*" if cites else ""))
    st.session_state.history.append({"role": "assistant", "content": answer})

    with col_activity:
        st.subheader("Agent activity")
        st.caption(f"route: {data.get('route')}  ·  usage: {data.get('usage', {}).get('used', '?')} tokens")
        for e in data.get("events", []):
            st.json(e, expanded=False)
