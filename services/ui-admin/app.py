"""ui-admin — Streamlit admin console (Administrator-only): document management + KB view.

    PYTHONPATH=../../libs ADMIN_URL=http://localhost:8800 streamlit run app.py
"""
from __future__ import annotations

import os

import httpx
import streamlit as st

ADMIN_URL = os.getenv("ADMIN_URL", "http://localhost:8800")

st.set_page_config(page_title="ABC Bank Admin", layout="wide")
st.title("ABC Bank — Admin Console")
st.caption("Administrator-only. Document management + knowledge base.")

tab_upload, tab_kb = st.tabs(["Add / update document", "Knowledge base"])

with tab_upload:
    doc_id = st.text_input("doc_id", "DOC-NEW-001")
    content = st.text_area("Markdown content (with --- front-matter ---)", height=240)
    if st.button("Index document"):
        try:
            r = httpx.post(f"{ADMIN_URL}/admin/documents", json={"doc_id": doc_id, "content": content}, timeout=30)
            st.success(r.json())
        except Exception as e:
            st.error(f"admin service unreachable: {e}")

with tab_kb:
    if st.button("Refresh"):
        try:
            st.json(httpx.get(f"{ADMIN_URL}/admin/kb", timeout=30).json())
        except Exception as e:
            st.error(f"admin service unreachable: {e}")
