"""ai-knowledge-service (retrieval) — READ path /search. docs/04, docs/09 §3."""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from contracts.models import RetrievalRequest, to_jsonable
from rag.store import get_index

app = FastAPI(title="ai-knowledge-retrieval")


class SearchBody(BaseModel):
    query: str
    top_k: int = 6
    filters: dict = {}
    rerank: bool = True
    access_level_max: str = "restricted"


@app.get("/health")
async def health():
    return {"status": "ok", "chunks": len(get_index().chunks)}


@app.post("/search")
async def search(body: SearchBody):
    req = RetrievalRequest(**body.model_dump())
    res = await get_index().search(req)
    return to_jsonable(res)
