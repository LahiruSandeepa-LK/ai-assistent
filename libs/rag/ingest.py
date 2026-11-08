"""Ingestion write path: load a document folder -> chunk -> index. docs/01 §3b, docs/04 §4."""
from __future__ import annotations

import os

from contracts.models import Chunk, Source
from .chunking import chunk_document
from .store import KnowledgeIndex, get_index


def ingest_text(index: KnowledgeIndex, raw: str, doc_id_fallback: str = "") -> int:
    doc_chunks = chunk_document(raw, doc_id_fallback=doc_id_fallback)
    chunks = [
        Chunk(
            chunk_id=dc.chunk_id,
            text=dc.text,
            source=Source(
                doc_id=dc.metadata.get("doc_id", doc_id_fallback),
                title=dc.metadata.get("title", ""),
                section=dc.section,
                url=dc.metadata.get("source_url", ""),
            ),
            metadata=dc.metadata,
        )
        for dc in doc_chunks
    ]
    index.upsert_chunks(chunks)
    return len(chunks)


def ingest_folder(path: str, index: KnowledgeIndex | None = None) -> dict[str, int]:
    """Ingest every .md under `path` (recursively). Returns {doc_id or filename: n_chunks}."""
    index = index or get_index()
    stats: dict[str, int] = {}
    for root, _dirs, files in os.walk(path):
        for fn in sorted(files):
            if not fn.endswith(".md") or fn.upper() in ("README.MD",):
                continue
            fp = os.path.join(root, fn)
            with open(fp, encoding="utf-8") as f:
                raw = f.read()
            n = ingest_text(index, raw, doc_id_fallback=os.path.splitext(fn)[0])
            # key by doc_id when present
            key = raw.split("doc_id:", 1)[1].splitlines()[0].strip() if "doc_id:" in raw else fn
            stats[key] = n
    return stats
