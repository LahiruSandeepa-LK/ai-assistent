"""ui-public — Streamlit chat + agent activity panel. docs/00 FE1-FE11.

    PYTHONPATH=../../libs API_URL=http://localhost:8000 streamlit run app.py
"""
from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="ABC Bank Assistant", layout="wide")
st.title("ABC Bank — AI Assistant")

with st.sidebar:
    role = st.selectbox("Sign in as (dev)", ["analyst", "viewer", "admin"])
    st.caption("Dev auth: the username is the bearer token.")

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
            headers={"Authorization": f"Bearer {role}"},
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
