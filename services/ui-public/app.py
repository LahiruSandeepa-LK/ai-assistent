"""ui-public — Streamlit chat + agent activity. docs/00 FE1-FE11.

Login (all in-window, no page navigation):
  * Primary: username / password against Keycloak (password grant). Works for public users
    (-> Viewer) and staff (-> Analyst/Administrator). Public demo account: public / Public#12345.
  * Optional: "Continue with SSO" (Authorization-Code redirect) for a brokered corporate IdP.
A dev fallback (role buttons) appears only when AUTH_MODE=dev so the demo runs offline.

    PYTHONPATH=../../libs API_URL=http://localhost:8000 streamlit run app.py
"""
from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8501")
AUTH_MODE = os.getenv("AUTH_MODE", "dev").lower()

st.set_page_config(page_title="ABC Bank Assistant", page_icon="🏦", layout="centered")


# PKCE verifiers pending an SSO redirect, keyed by state. st.cache_resource is a true process-wide
# singleton (survives Streamlit reruns and the fresh session after the redirect) — the only place
# the verifier reliably persists across the round-trip.
@st.cache_resource
def _pkce_store() -> dict:
    return {}


_PENDING: dict = _pkce_store()


def _handle_sso_callback() -> bool:
    """Complete an Authorization-Code redirect if Keycloak returned ?code=."""
    code = st.query_params.get("code")
    state = st.query_params.get("state")
    if not code:
        return False
    verifier = _PENDING.pop(state, "")
    st.query_params.clear()
    if not verifier:
        st.warning("Your sign-in session expired. Please sign in again.")
        return False
    try:
        from authclient.keycloak_client import exchange_code

        tok = exchange_code(code, f"{PUBLIC_BASE_URL}/", verifier)
        st.session_state.token = tok.get("access_token")
        st.session_state.identity = "sso"
        return True
    except Exception as e:
        st.error(f"SSO sign-in failed: {e}")
        return False


def _password_login(username: str, password: str) -> tuple[str | None, str]:
    """Keycloak password grant (in-window). Dev fallback when offline."""
    try:
        from authclient.keycloak_client import password_login

        tok = password_login(username, password)
        return tok.get("access_token"), ""
    except Exception as e:
        if AUTH_MODE == "dev":
            return username.strip().lower(), ""   # offline: username is the dev token
        return None, f"sign-in failed: check your username/password ({e})"


def _login_view():
    st.title("🏦 ABC Bank — AI Assistant")
    st.caption("Sign in to ask about policies, incidents and runbooks.")

    with st.form("signin", clear_on_submit=False):
        u = st.text_input("Username", placeholder="public")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", use_container_width=True, type="primary"):
            token, err = _password_login(u, p)
            if token:
                st.session_state.token = token
                st.session_state.identity = "user"
                st.rerun()
            else:
                st.error(err)

    st.caption("Public demo: **public / Public#12345** (read-only) · "
               "Staff: **admin / Admin#12345**, **analyst / Analyst#12345**")

    with st.expander("Other sign-in options"):
        # SSO (Authorization-Code redirect) — for a brokered corporate IdP. This navigates to
        # Keycloak and returns here signed in.
        try:
            from authclient.keycloak_client import issuer, new_pkce, sso_login_url
            import secrets as _s

            verifier, challenge = new_pkce()
            state = _s.token_urlsafe(12)
            _PENDING[state] = verifier
            st.link_button("Continue with SSO →",
                           sso_login_url(f"{PUBLIC_BASE_URL}/", code_challenge=challenge, state=state),
                           use_container_width=True)
            st.caption("Opens Keycloak (or your corporate IdP) in this window; you return signed in "
                       "with read-only (Viewer) access.")
            reg = (f"{issuer()}/protocol/openid-connect/registrations?client_id="
                   f"{os.getenv('KEYCLOAK_WEB_CLIENT_ID','ai-assistant-web')}&response_type=code"
                   f"&scope=openid&redirect_uri={PUBLIC_BASE_URL}/")
            st.link_button("Create an account", reg, use_container_width=True)
        except Exception as e:
            st.caption(f"(SSO unavailable: {e})")

        if AUTH_MODE == "dev":
            st.caption("Dev quick sign-in (offline):")
            cols = st.columns(3)
            for i, role in enumerate(["viewer", "analyst", "admin"]):
                if cols[i].button(role, key=f"dev-{role}", use_container_width=True):
                    st.session_state.token = role
                    st.session_state.identity = "dev"
                    st.rerun()


def _fetch_history() -> list[dict]:
    """The user's previous sessions (read-only). Never fed to the agent."""
    try:
        r = httpx.get(f"{API_URL}/api/history",
                      params={"session_id": st.session_state.get("sid", "")},
                      headers={"Authorization": f"Bearer {st.session_state.token}"}, timeout=15)
        return r.json().get("sessions", []) if r.status_code == 200 else []
    except Exception:
        return []


def _chat_view():
    import uuid
    # a fresh session id per login — a new session starts with an empty chat and no prior history
    st.session_state.setdefault("sid", uuid.uuid4().hex)

    with st.sidebar:
        st.markdown(f"**Signed in** · {st.session_state.get('identity','')}")
        c1, c2 = st.columns(2)
        if c1.button("New chat", use_container_width=True):
            for k in ("sid", "history", "last"):
                st.session_state.pop(k, None)
            st.rerun()
        if c2.button("Sign out", use_container_width=True):
            for k in ("token", "identity", "history", "last", "sid"):
                st.session_state.pop(k, None)
            st.rerun()

        # --- Recent conversations (last 3 sessions), shown separately, read-only ---
        st.divider()
        st.markdown("**Recent conversations**")
        sessions = _fetch_history()
        if not sessions:
            st.caption("No earlier conversations yet.")
        for sess in sessions:
            with st.expander(sess.get("title") or "Conversation", expanded=False):
                for role, text in sess.get("turns", []):
                    who = "You" if role == "user" else "Assistant"
                    st.markdown(f"**{who}:** {text}")

        last = st.session_state.get("last")
        if last:
            st.divider()
            st.caption(f"route: **{last.get('route','?')}** · "
                       f"usage: {last.get('usage',{}).get('used','?')} tokens")
            with st.expander("Agent activity", expanded=False):
                for e in last.get("events", []):
                    st.json(e, expanded=False)

    st.title("🏦 ABC Bank — AI Assistant")

    for turn in st.session_state.get("history", []):
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])

    prompt = st.chat_input("Ask about policies, incidents, runbooks…")
    if not prompt:
        return

    st.session_state.setdefault("history", []).append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                r = httpx.post(
                    f"{API_URL}/api/chat",
                    headers={"Authorization": f"Bearer {st.session_state.token}"},
                    json={"session_id": st.session_state["sid"], "message": prompt},
                    timeout=60,
                )
                if r.status_code == 401:
                    st.error("Your session expired — please sign out and sign in again.")
                    return
                data = r.json()
            except Exception as e:
                data = {"answer": f"(API unreachable: {e})", "route": "error", "events": [], "citations": []}
        answer = data.get("answer", "")
        st.markdown(answer)
        # show sources as friendly document titles (deduplicated), never raw internal IDs
        titles = []
        for c in data.get("citations", []):
            t = c.get("title") or ""
            if t and t not in titles:
                titles.append(t)
        if titles and data.get("route") not in ("greeting", "context", "blocked", "out_of_scope"):
            st.caption("Sources: " + " · ".join(titles[:3]))

    st.session_state.history.append({"role": "assistant", "content": answer})
    st.session_state.last = data


# ---- entry ----
_handle_sso_callback()
if "token" not in st.session_state:
    _login_view()
else:
    _chat_view()
