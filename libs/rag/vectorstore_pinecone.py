"""Real Pinecone vector-store adapter. Same interface as InMemoryVectorStore, so it drops
into KnowledgeIndex unchanged (store.py calls get_vector_store()). Activated when
PINECONE_API_KEY is set. docs/04 §3, ADR-002.

Design notes
------------
* Lazy index creation: the index is created on the first upsert using the embedding
  dimension of the incoming vectors, so this works with ANY embedder (the offline
  HashingEmbedder is 256-dim; OpenAI text-embedding-3-small is 1536) without config.
* Metric is cosine, matching embeddings.cosine() used offline.
* delete(doc_id): Pinecone serverless does not support delete-by-metadata-filter, so we
  keep an in-process doc_id -> chunk_ids map (populated on upsert) and delete by id, with
  a metadata-filter delete as the fallback for pod indexes / cross-process deletes.
* Env: PINECONE_API_KEY (required; "pclocal" for the local emulator), PINECONE_INDEX
  (default "ai-assistant"), PINECONE_NAMESPACE (default ""), PINECONE_CLOUD (default "aws"),
  PINECONE_REGION (default "us-east-1").
* Local emulator: set PINECONE_HOST to the Pinecone Local controller (e.g.
  http://pinecone-local:5080). The adapter then connects to the emulator instead of the managed
  cloud — real Pinecone API, no account needed. docs/04 §3, ADR-002.
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

from .vectorstore import VectorRecord


class PineconeVectorStore:  # pragma: no cover - requires a live Pinecone (cloud or local emulator)
    def __init__(self) -> None:
        from pinecone import Pinecone  # modern SDK (pinecone>=3)

        self._host = os.getenv("PINECONE_HOST", "")  # set -> Pinecone Local emulator
        kw = {"api_key": os.environ["PINECONE_API_KEY"]}
        if self._host:
            kw["host"] = self._host
        self._pc = Pinecone(**kw)
        self._name = os.getenv("PINECONE_INDEX", "ai-assistant")
        self._namespace = os.getenv("PINECONE_NAMESPACE", "")
        self._cloud = os.getenv("PINECONE_CLOUD", "aws")
        self._region = os.getenv("PINECONE_REGION", "us-east-1")
        self._index = None
        # doc_id -> set(chunk_id) so deletes are reliable on serverless indexes.
        self._doc_ids: dict[str, set[str]] = defaultdict(set)

    # ---- index lifecycle ----
    def _ensure_index(self, dim: int):
        if self._index is not None:
            return self._index
        from pinecone import ServerlessSpec

        existing = {i["name"] for i in self._pc.list_indexes()}
        if self._name not in existing:
            self._pc.create_index(
                name=self._name,
                dimension=dim,
                metric="cosine",
                spec=ServerlessSpec(cloud=self._cloud, region=self._region),
            )
        # The emulator returns a per-index host; the SDK resolves it from describe_index. Pass the
        # host explicitly so cross-container access works against Pinecone Local.
        try:
            host = self._pc.describe_index(self._name).host
            self._index = self._pc.Index(host=host) if host else self._pc.Index(self._name)
        except Exception:
            self._index = self._pc.Index(self._name)
        return self._index

    # ---- write path ----
    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        index = self._ensure_index(len(records[0].vector))
        vectors = []
        for r in records:
            doc_id = r.payload.get("doc_id")
            if doc_id:
                self._doc_ids[doc_id].add(r.chunk_id)
            # Pinecone metadata values must be str/num/bool/list[str]; coerce others.
            meta = {k: v for k, v in r.payload.items() if isinstance(v, (str, int, float, bool))}
            vectors.append({"id": r.chunk_id, "values": r.vector, "metadata": meta})
        # Batch to stay within request limits.
        for i in range(0, len(vectors), 100):
            index.upsert(vectors=vectors[i : i + 100], namespace=self._namespace)

    def delete(self, doc_id: str) -> int:
        if self._index is None:
            return 0
        ids = list(self._doc_ids.get(doc_id, set()))
        if ids:
            for i in range(0, len(ids), 1000):
                self._index.delete(ids=ids[i : i + 1000], namespace=self._namespace)
            self._doc_ids.pop(doc_id, None)
            return len(ids)
        # Fallback for pod indexes / ids not tracked in this process.
        try:
            self._index.delete(filter={"doc_id": {"$eq": doc_id}}, namespace=self._namespace)
        except Exception:
            return 0
        return 0

    # ---- read path ----
    def query(self, vector: list[float], top_k: int = 20) -> list[tuple[str, float]]:
        index = self._ensure_index(len(vector))
        res = index.query(
            vector=vector,
            top_k=top_k,
            include_values=False,
            include_metadata=False,
            namespace=self._namespace,
        )
        matches = res.get("matches", []) if isinstance(res, dict) else getattr(res, "matches", [])
        out: list[tuple[str, float]] = []
        for m in matches:
            mid = m["id"] if isinstance(m, dict) else m.id
            score = m["score"] if isinstance(m, dict) else m.score
            out.append((mid, float(score)))
        return out

    def __len__(self) -> int:
        if self._index is None:
            return 0
        try:
            stats = self._index.describe_index_stats()
            total = stats.get("total_vector_count") if isinstance(stats, dict) else stats.total_vector_count
            return int(total or 0)
        except Exception:
            return sum(len(s) for s in self._doc_ids.values())
