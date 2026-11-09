"""Runs an ingestion job: bytes -> extract text -> chunk -> index, updating the JobStore so the
admin UI can show live progress. Supports md/txt/html (stdlib) and pdf/docx/xlsx (optional libs,
via the document-parser tool). docs/04 §4, docs/09.
"""
from __future__ import annotations

import os
import re
import tempfile

from contracts.models import Chunk, Source
from rag.chunking import chunk_document
from rag.store import get_index
from orchestrator.tool_docparser import extract_text
from .jobs import get_job_store

# formats whose bytes we write to a temp file so the parser can read them natively
_BINARY_EXT = (".pdf", ".docx", ".xlsx", ".xlsm", ".xltx")


def _to_text(data: bytes, filename: str) -> tuple[str, str]:
    name = (filename or "").lower()
    if name.endswith(_BINARY_EXT):
        suffix = os.path.splitext(name)[1]
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            return extract_text(tmp_path, filename=filename)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    # text formats: decode directly
    return extract_text(data.decode("utf-8", errors="ignore"), filename=filename)


def run_ingest_job(job_id: str, data: bytes, filename: str, doc_id: str,
                   access_level: str = "internal", title: str = "") -> None:
    """Execute a job end-to-end, recording progress at each stage. Safe to run in a thread or
    FastAPI BackgroundTask."""
    jobs = get_job_store()
    try:
        jobs.update(job_id, stage="extracting", message=f"Extracting text from {filename}")
        text, fmt = _to_text(data, filename)
        stripped = text.strip()
        # parser returns a '[<fmt> parsing requires the "<pkg>" package]' placeholder when an
        # optional lib is missing; match that exact shape, not any leading '[' (a real doc may
        # legitimately start with '[', e.g. '[DRAFT]' or a reference-style link).
        is_placeholder = bool(re.match(r"^\[.*(requires|parsing).*\]$", stripped))
        if not stripped or is_placeholder:
            jobs.update(job_id, stage="failed", error=stripped or "no extractable text",
                        message="Extraction failed")
            return

        jobs.update(job_id, stage="chunking", message="Chunking document")
        front = (f"---\ndoc_id: {doc_id}\ntitle: {title or filename}\n"
                 f"access_level: {access_level}\nsource_type: {fmt}\n---\n\n{text}")
        doc_chunks = chunk_document(front, doc_id_fallback=doc_id)
        if not doc_chunks:
            jobs.update(job_id, stage="failed", error="no chunks produced", message="Chunking failed")
            return

        jobs.update(job_id, stage="indexing", message=f"Indexing {len(doc_chunks)} chunks")
        index = get_index()
        chunks = [
            Chunk(chunk_id=dc.chunk_id, text=dc.text,
                  source=Source(doc_id=dc.metadata.get("doc_id", doc_id),
                                title=dc.metadata.get("title", title or filename),
                                section=dc.section, url=dc.metadata.get("source_url", "")),
                  metadata=dc.metadata)
            for dc in doc_chunks
        ]
        index.upsert_chunks(chunks)
        jobs.update(job_id, stage="done", progress=100, chunks=len(chunks),
                    message=f"Indexed {len(chunks)} chunks from {filename}")
    except Exception as e:  # pragma: no cover - defensive
        jobs.update(job_id, stage="failed", error=str(e), message="Ingestion error")
