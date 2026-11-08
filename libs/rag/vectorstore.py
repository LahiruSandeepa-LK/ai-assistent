"""Vector store. Default = in-memory cosine index (offline). Pinecone adapter used
when PINECONE_API_KEY is set. docs/04 §3, ADR-002."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .embeddings import cosine


@dataclass
class VectorRecord:
    chunk_id: str
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)


class InMemoryVectorStore:
    def __init__(self):
        self._records: dict[str, VectorRecord] = {}

    def upsert(self, records: list[VectorRecord]) -> None:
        for r in records:
            self._records[r.chunk_id] = r

    def delete(self, doc_id: str) -> int:
        to_del = [cid for cid, r in self._records.items() if r.payload.get("doc_id") == doc_id]
        for cid in to_del:
            del self._records[cid]
        return len(to_del)

    def query(self, vector: list[float], top_k: int = 20) -> list[tuple[str, float]]:
        scored = [(cid, cosine(vector, r.vector)) for cid, r in self._records.items()]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self._records)


def get_vector_store():
    """Return the configured vector store; in-memory offline, Pinecone if configured."""
    if os.getenv("PINECONE_API_KEY"):
        try:  # pragma: no cover
            from .vectorstore_pinecone import PineconeVectorStore  # type: ignore

            return PineconeVectorStore()
        except Exception:
            pass
    return InMemoryVectorStore()
