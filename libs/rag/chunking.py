"""Section-aware chunking with front-matter metadata. docs/04-rag-retrieval.md §4."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedDoc:
    metadata: dict[str, Any]
    body: str


@dataclass
class DocChunk:
    chunk_id: str
    text: str
    section: str
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_frontmatter(text: str) -> ParsedDoc:
    """Parse a leading YAML-ish `--- ... ---` block (simple key: value lines)."""
    meta: dict[str, Any] = {}
    body = text
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            raw, body = parts[1], parts[2]
            for line in raw.strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
    return ParsedDoc(metadata=meta, body=body.strip())


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, section_text) by '#'/'##' headings."""
    sections: list[tuple[str, str]] = []
    current_head = "Overview"
    buf: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^#{1,6}\s+(.*)$", line.strip())
        if m:
            if buf:
                sections.append((current_head, "\n".join(buf).strip()))
                buf = []
            current_head = m.group(1).strip()
        else:
            buf.append(line)
    if buf:
        sections.append((current_head, "\n".join(buf).strip()))
    return [(h, t) for h, t in sections if t]


def _window(text: str, max_tokens: int, overlap: int) -> list[str]:
    """Approximate token windowing by whitespace words (1 token ~ 0.75 words)."""
    words = text.split()
    max_words = int(max_tokens * 0.75)
    ov_words = int(overlap * 0.75)
    if len(words) <= max_words:
        return [text]
    out: list[str] = []
    i = 0
    while i < len(words):
        out.append(" ".join(words[i : i + max_words]))
        i += max_words - ov_words
    return out


def chunk_document(
    text: str, *, doc_id_fallback: str = "", max_tokens: int = 700, overlap: int = 100
) -> list[DocChunk]:
    parsed = parse_frontmatter(text)
    meta = dict(parsed.metadata)
    doc_id = meta.get("doc_id") or doc_id_fallback
    # Metadata header is indexed WITH each chunk so queries on doc_id / title / date match
    # on both the sparse and dense paths (fixes date/ID-specific retrieval precision).
    header_bits = [b for b in (doc_id, meta.get("title", ""), meta.get("created_date", "")) if b]
    header = " | ".join(header_bits)
    chunks: list[DocChunk] = []
    ordinal = 0
    for heading, sec_text in _split_sections(parsed.body):
        for piece in _window(sec_text, max_tokens, overlap):
            ordinal += 1
            cid = hashlib.sha256(f"{doc_id}:{heading}:{ordinal}".encode()).hexdigest()[:24]
            cmeta = dict(meta)
            cmeta["section"] = heading
            text = f"{header} | {heading}\n{piece}" if header else f"{heading}\n{piece}"
            chunks.append(DocChunk(chunk_id=cid, text=text, section=heading, metadata=cmeta))
    return chunks
