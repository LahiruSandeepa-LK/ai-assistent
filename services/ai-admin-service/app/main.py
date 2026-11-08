"""ai-admin-service — admin backend: document management + analytics/eval. docs/13, ADR-009."""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from rag.ingest import ingest_text
from rag.store import get_index

app = FastAPI(title="ai-admin-service")


class DocUpload(BaseModel):
    doc_id: str
    content: str


@app.get("/health")
async def health():
    idx = get_index()
    return {"status": "ok", "documents": len({c.source.doc_id for c in idx.chunks.values()}),
            "chunks": len(idx.chunks)}


@app.post("/admin/documents")
async def upload(body: DocUpload):
    n = ingest_text(get_index(), body.content, doc_id_fallback=body.doc_id)
    return {"doc_id": body.doc_id, "status": "indexed", "chunks": n}


@app.delete("/admin/documents/{doc_id}")
async def delete(doc_id: str):
    n = get_index().delete_doc(doc_id)
    return {"doc_id": doc_id, "status": "deleted", "removed": n}


@app.get("/admin/kb")
async def kb():
    idx = get_index()
    docs: dict[str, int] = {}
    for c in idx.chunks.values():
        docs[c.source.doc_id] = docs.get(c.source.doc_id, 0) + 1
    return {"documents": docs}
