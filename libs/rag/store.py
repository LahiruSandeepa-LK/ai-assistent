"""KnowledgeIndex: the read+write RAG engine tying chunks, BM25, embeddings and the
vector store together. Backs ai-knowledge-service. docs/04, docs/13."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from contracts.models import Chunk, RetrievalRequest, RetrievalResult, Source
from authz.rbac import ACCESS_ORDER, access_allowed
from .bm25 import BM25
from .embeddings import get_embedder
from .hybrid import keyword_overlap_rerank, rrf_fuse
from .vectorstore import InMemoryVectorStore, VectorRecord, get_vector_store


class KnowledgeIndex:
    def __init__(self):
        self.chunks: dict[str, Chunk] = {}
        self.embedder = get_embedder()
        self.vectors = get_vector_store()
        self.bm25 = BM25()
        self._dirty = True
        # Cross-process sharing for the offline (in-memory) store: when INDEX_PATH is set, the
        # chunk set is snapshotted to a shared file so a doc uploaded by ai-admin-service becomes
        # searchable by the chat process (ai-assistant-api). Pinecone is already shared, so file
        # persistence only applies to the in-memory store. docs/04 §3.
        self._path = os.getenv("INDEX_PATH", "")
        self._shared = bool(self._path) and isinstance(self.vectors, InMemoryVectorStore)
        self._mtime = 0.0
        if self._shared:
            self._load()

    # ---- write path ----
    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        self._maybe_reload()
        recs = []
        for c in chunks:
            self.chunks[c.chunk_id] = c
            recs.append(
                VectorRecord(
                    chunk_id=c.chunk_id,
                    vector=self.embedder.embed(c.text),
                    payload={"doc_id": c.source.doc_id, **c.metadata},
                )
            )
        self.vectors.upsert(recs)
        self._dirty = True
        self._save()

    def delete_doc(self, doc_id: str) -> int:
        self._maybe_reload()
        n = self.vectors.delete(doc_id)
        for cid in [cid for cid, c in self.chunks.items() if c.source.doc_id == doc_id]:
            del self.chunks[cid]
        self._dirty = True
        self._save()
        return n

    # ---- shared-file persistence (offline cross-process index) ----
    def _save(self) -> None:
        if not self._shared:
            return
        rows = [{"chunk_id": c.chunk_id, "text": c.text, "doc_id": c.source.doc_id,
                 "title": c.source.title, "section": c.source.section, "url": c.source.url,
                 "metadata": c.metadata} for c in self.chunks.values()]
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"chunks": rows}, f)
        os.replace(tmp, self._path)
        try:
            self._mtime = os.path.getmtime(self._path)
        except OSError:
            pass

    def _maybe_reload(self) -> None:
        if not self._shared:
            return
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            return
        if mtime != self._mtime:
            self._load()

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                payload = json.load(f)
            self._mtime = os.path.getmtime(self._path)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        # rebuild chunks + vectors from the snapshot (vectors re-embedded; bm25 refits lazily)
        self.chunks = {}
        self.vectors = InMemoryVectorStore()
        recs = []
        for r in payload.get("chunks", []):
            c = Chunk(chunk_id=r["chunk_id"], text=r["text"],
                      source=Source(doc_id=r["doc_id"], title=r.get("title", ""),
                                    section=r.get("section", ""), url=r.get("url", "")),
                      metadata=r.get("metadata", {}))
            self.chunks[c.chunk_id] = c
            recs.append(VectorRecord(chunk_id=c.chunk_id, vector=self.embedder.embed(c.text),
                                     payload={"doc_id": c.source.doc_id, **c.metadata}))
        self.vectors.upsert(recs)
        self._dirty = True

    def _refit_bm25(self) -> None:
        if self._dirty:
            self.bm25.fit([(cid, c.text) for cid, c in self.chunks.items()])
            self._dirty = False

    # ---- read path ----
    async def search(self, req: RetrievalRequest) -> RetrievalResult:
        self._maybe_reload()
        self._refit_bm25()

        async def _dense():
            qv = self.embedder.embed(req.query)
            return self.vectors.query(qv, top_k=max(req.top_k * 5, 20))

        async def _sparse():
            return self.bm25.search(req.query, top_k=max(req.top_k * 5, 20))

        dense, sparse = await asyncio.gather(_dense(), _sparse())

        fused = rrf_fuse(dense, sparse)
        # candidate set
        cand_ids = sorted(fused, key=lambda c: fused[c], reverse=True)[: max(req.top_k * 3, 15)]

        # rerank (dependency-free overlap stand-in for a cross-encoder)
        if req.rerank:
            rr = keyword_overlap_rerank(req.query, {cid: self.chunks[cid].text for cid in cand_ids}, cand_ids)
            cand_ids.sort(key=lambda c: (rr.get(c, 0.0), fused[c]), reverse=True)

        # access-level filter + metadata filters
        out: list[Chunk] = []
        dmap = dict(dense)
        smap = dict(sparse)
        for cid in cand_ids:
            c = self.chunks[cid]
            lvl = str(c.metadata.get("access_level", "internal"))
            if lvl in ACCESS_ORDER and not access_allowed(req.access_level_max, lvl):
                continue
            if not _passes_filters(c.metadata, req.filters):
                continue
            c.dense_score = dmap.get(cid, 0.0)
            c.sparse_score = smap.get(cid, 0.0)
            c.score = fused.get(cid, 0.0)
            out.append(c)
            if len(out) >= req.top_k:
                break
        return RetrievalResult(chunks=out, degraded=False)


def _passes_filters(meta: dict[str, Any], filters: dict[str, Any]) -> bool:
    for k, v in (filters or {}).items():
        if k not in meta:
            return False
        if isinstance(v, (list, tuple, set)):
            if meta[k] not in v:
                return False
        elif str(meta[k]) != str(v):
            return False
    return True


# process-wide singleton for the POC (a real deployment persists to Pinecone)
_INDEX: KnowledgeIndex | None = None


def get_index() -> KnowledgeIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = KnowledgeIndex()
    return _INDEX
