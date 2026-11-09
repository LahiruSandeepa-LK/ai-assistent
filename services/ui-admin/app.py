"""ui-admin — Streamlit admin console (Administrator-only).

Login: username/password (Keycloak Resource-Owner Password grant; dev fallback offline).
Features: document upload (pdf/docx/xlsx/md/txt/html) with live indexing progress, runtime LLM
configuration (create-only; API key is write-only and never displayed), and a KB view.

    PYTHONPATH=../../libs ADMIN_URL=http://localhost:8800 streamlit run app.py
"""
from __future__ import annotations

import os
import time

import httpx
import streamlit as st

ADMIN_URL = os.getenv("ADMIN_URL", "http://localhost:8800")
AUTH_MODE = os.getenv("AUTH_MODE", "dev").lower()

st.set_page_config(page_title="ABC Bank Admin", layout="wide")


def authenticate(username: str, password: str) -> tuple[str | None, str]:
    """Return (bearer_token, error). Keycloak password grant; dev fallback when offline."""
    try:
        from authclient.keycloak_client import password_login

        tok = password_login(username, password)
        return tok.get("access_token"), ""
    except Exception as e:
        if AUTH_MODE == "dev":
            # offline/dev: the API resolves the username itself as the bearer token
            return username.strip().lower(), ""
        return None, f"login failed: {e}"


def _auth_header() -> dict:
    return {"Authorization": f"Bearer {st.session_state.get('token','')}"}


# ---- login gate ----
if "token" not in st.session_state:
    st.title("ABC Bank — Admin Console")
    st.caption("Administrator sign-in (username / password).")
    with st.form("login"):
        u = st.text_input("Username", value="admin" if AUTH_MODE == "dev" else "")
        p = st.text_input("Password", type="password",
                          help="Dev mode: any password; use username 'admin'.")
        if st.form_submit_button("Sign in"):
            token, err = authenticate(u, p)
            if token:
                st.session_state.token = token
                st.rerun()
            else:
                st.error(err)
    st.stop()

st.title("ABC Bank — Admin Console")
with st.sidebar:
    st.success("Signed in")
    if st.button("Sign out"):
        del st.session_state.token
        st.rerun()

tab_upload, tab_llm, tab_kb = st.tabs(["Upload documents", "LLM configuration", "Knowledge base"])

# ---- document upload with live progress ----
with tab_upload:
    st.subheader("Upload & index a document")
    doc_id = st.text_input("doc_id", "DOC-UP-001")
    access = st.selectbox("Access level", ["public", "internal", "confidential"], index=1)
    up = st.file_uploader("File", type=["pdf", "docx", "xlsx", "md", "txt", "html"])
    if st.button("Upload & index", disabled=up is None):
        try:
            files = {"file": (up.name, up.getvalue())}
            data = {"doc_id": doc_id, "access_level": access, "title": up.name}
            r = httpx.post(f"{ADMIN_URL}/admin/documents/upload", files=files, data=data,
                           headers=_auth_header(), timeout=60)
            if r.status_code == 403:
                st.error("Administrator role required.")
            else:
                job_id = r.json()["job_id"]
                bar = st.progress(0, text="queued")
                status = st.empty()
                for _ in range(120):
                    jr = httpx.get(f"{ADMIN_URL}/admin/jobs/{job_id}", headers=_auth_header(), timeout=10).json()
                    bar.progress(jr["progress"] / 100, text=f"{jr['stage']} — {jr.get('message','')}")
                    if jr["stage"] in ("done", "failed"):
                        if jr["stage"] == "done":
                            status.success(f"Indexed {jr['chunks']} chunks from {jr['filename']}")
                        else:
                            status.error(f"Failed: {jr.get('error','')}")
                        break
                    time.sleep(0.5)
        except Exception as e:
            st.error(f"admin service unreachable: {e}")

# ---- LLM configuration ----
with tab_llm:
    st.subheader("Configure the active LLM")
    st.caption("Create-only. The API key is write-only — it is stored securely and never shown "
               "again or returned by the API.")
    with st.form("llm"):
        provider = st.selectbox("Provider", ["gemini", "anthropic", "openai", "mock"])
        c1, c2 = st.columns(2)
        model_strong = c1.text_input("Model (strong)", "")
        model_fast = c2.text_input("Model (fast)", "")
        label = st.text_input("Label (optional)", "")
        api_key = st.text_input("API key", type="password",
                                help="Write-only. Not required for the 'mock' provider.")
        if st.form_submit_button("Create & activate"):
            try:
                payload = {"provider": provider, "model_strong": model_strong,
                           "model_fast": model_fast, "label": label, "api_key": api_key,
                           "activate": True}
                r = httpx.post(f"{ADMIN_URL}/admin/llm", json=payload, headers=_auth_header(), timeout=20)
                if r.status_code == 201:
                    st.success(f"Created & activated config {r.json()['id']} ({provider}).")
                elif r.status_code == 403:
                    st.error("Administrator role required.")
                else:
                    st.error(r.text)
            except Exception as e:
                st.error(f"admin service unreachable: {e}")

    st.markdown("**Existing configurations**")
    try:
        cfgs = httpx.get(f"{ADMIN_URL}/admin/llm", headers=_auth_header(), timeout=10).json().get("configs", [])
        for c in cfgs:
            cols = st.columns([3, 2, 2, 1])
            flag = "✅ active" if c["active"] else ""
            cols[0].write(f"**{c['provider']}** {flag}  \n`{c['id']}` {c.get('label','')}")
            cols[1].write(f"strong: {c['model_strong'] or '—'}")
            cols[2].write(f"key set: {'yes' if c['has_secret'] else 'no'}")
            if not c["active"] and cols[3].button("Activate", key=f"act-{c['id']}"):
                httpx.post(f"{ADMIN_URL}/admin/llm/{c['id']}/activate", headers=_auth_header(), timeout=10)
                st.rerun()
    except Exception as e:
        st.caption(f"(could not load configs: {e})")

# ---- knowledge base ----
with tab_kb:
    if st.button("Refresh KB"):
        try:
            st.json(httpx.get(f"{ADMIN_URL}/admin/kb", headers=_auth_header(), timeout=30).json())
        except Exception as e:
            st.error(f"admin service unreachable: {e}")
