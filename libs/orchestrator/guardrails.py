"""Guardrails: input prompt-injection screen, output citation integrity + sensitive-data.
docs/06-security-guardrails.md §1-3."""
from __future__ import annotations

import re

from contracts.models import Chunk

INJECTION_PATTERNS = [
    r"ignore (all|any|previous|above) (instructions|prompts)",
    r"disregard (the )?(system|previous) (prompt|instructions)",
    r"reveal (your )?(system prompt|instructions|api key|secret)",
    r"print (your )?(system prompt|credentials|secret)",
    r"you are now (a|an|in) ",
    r"exfiltrate|data exfiltration",
]

SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9]{10,}",      # api-key-like
    r"AKIA[0-9A-Z]{16}",          # aws-key-like
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
]


def screen_input(text: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means blocked as a likely prompt injection."""
    low = text.lower()
    for pat in INJECTION_PATTERNS:
        if re.search(pat, low):
            return False, "input blocked: possible prompt-injection attempt"
    return True, ""


def sanitize_retrieved(text: str) -> str:
    """Neutralise instruction-like content embedded in retrieved documents (indirect injection)."""
    out = text
    for pat in INJECTION_PATTERNS:
        out = re.sub(pat, "[removed]", out, flags=re.IGNORECASE)
    return out


def redact_secrets(text: str) -> str:
    out = text
    for pat in SECRET_PATTERNS:
        out = re.sub(pat, "[redacted]", out)
    return out


def check_citations(answer: str, chunks: list[Chunk]) -> tuple[bool, list[str]]:
    """Every [DOC_ID] cited in the answer must be in the retrieved set. Returns
    (ok, hallucinated_ids)."""
    cited = set(re.findall(r"\[([A-Z0-9\-]+)\]", answer))
    retrieved = {c.source.doc_id for c in chunks}
    hallucinated = sorted(cited - retrieved)
    return (len(hallucinated) == 0, hallucinated)


def groundedness(answer: str, chunks: list[Chunk]) -> float:
    """Crude groundedness proxy: fraction of answer tokens present in the context."""
    from rag.embeddings import tokenize

    ctx = set()
    for c in chunks:
        ctx |= set(tokenize(c.text))
    ans = [t for t in tokenize(answer) if len(t) > 3]
    if not ans:
        return 0.0
    return sum(1 for t in ans if t in ctx) / len(ans)
