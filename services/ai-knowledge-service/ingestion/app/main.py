"""ai-knowledge-service (ingestion) — WRITE path /ingest. docs/01 §3b, docs/09 §3b."""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from rag.ingest import ingest_text
from rag.store import get_index

app = FastAPI(title="ai-knowledge-ingest")


class DocumentOp(BaseModel):
    op: str = "upsert"  # upsert | delete
    doc_id: str
    content: str | None = None


@app.get("/health")
async def health():
    return {"status": "ok", "chunks": len(get_index().chunks)}


@app.post("/ingest")
async def ingest(op: DocumentOp):
    idx = get_index()
    if op.op == "delete":
        n = idx.delete_doc(op.doc_id)
        return {"doc_id": op.doc_id, "status": "deleted", "removed": n}
    n = ingest_text(idx, op.content or "", doc_id_fallback=op.doc_id)
    return {"doc_id": op.doc_id, "status": "indexed", "chunks": n}
