"""Document parser tool. Extracts text from md/txt/html (stdlib) and pdf/docx (optional libs).
Returns Chunks (section-aware) so parsed content flows through the normal pipeline. docs/09 §4."""
from __future__ import annotations

import os
import re

from contracts.models import Chunk, Source
from rag.chunking import chunk_document


def _strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_text(source: str, filename: str = "") -> tuple[str, str]:
    """Return (text, fmt). `source` is a file path or raw content."""
    path = source if os.path.isfile(source) else ""
    name = (filename or path or "").lower()
    if path:
        if name.endswith(".pdf"):
            try:  # optional
                from pypdf import PdfReader  # type: ignore

                reader = PdfReader(path)
                return ("\n".join((p.extract_text() or "") for p in reader.pages), "pdf")
            except Exception:
                return ("[pdf parsing requires the 'pypdf' package]", "pdf")
        if name.endswith(".docx"):
            try:  # optional
                import docx  # type: ignore

                return ("\n".join(p.text for p in docx.Document(path).paragraphs), "docx")
            except Exception:
                return ("[docx parsing requires the 'python-docx' package]", "docx")
        with open(path, encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    else:
        raw = source
    if name.endswith(".html") or name.endswith(".htm") or raw.lstrip().startswith("<"):
        return (_strip_html(raw), "html")
    return (raw, "md" if name.endswith(".md") else "text")


def parse(source: str, filename: str = "", doc_id: str = "PARSED") -> list[Chunk]:
    text, fmt = extract_text(source, filename)
    # reuse the section-aware chunker; prepend minimal front-matter so metadata flows
    doc = f"---\ndoc_id: {doc_id}\ntitle: Parsed document ({fmt})\naccess_level: internal\n---\n\n{text}"
    chunks: list[Chunk] = []
    for dc in chunk_document(doc, doc_id_fallback=doc_id):
        chunks.append(Chunk(chunk_id=dc.chunk_id, text=dc.text,
                            source=Source(doc_id=doc_id, title=f"Parsed ({fmt})", section=dc.section),
                            metadata=dc.metadata, score=1.0))
    return chunks or [Chunk(chunk_id=f"{doc_id}-0", text=text[:500],
                            source=Source(doc_id=doc_id, title=f"Parsed ({fmt})", section="body"), score=1.0)]
