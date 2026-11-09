"""Guardrails: input prompt-injection screen, topical scope filter, output citation integrity +
sensitive-data redaction. docs/06-security-guardrails.md §1-4."""
from __future__ import annotations

import os
import re

from contracts.models import Chunk

# ---- topical scope: the assistant only answers ABC Bank banking questions ----
# Broad in-domain vocabulary (fast path). Keep generous to avoid rejecting valid paraphrases.
DOMAIN_KEYWORDS = {
    "bank", "banking", "abc bank", "account", "savings", "current account", "deposit", "fixed deposit",
    "fd", "withdraw", "withdrawal", "balance", "statement", "passbook", "loan", "loans", "borrow",
    "mortgage", "home loan", "housing loan", "personal loan", "education loan", "pension", "leasing",
    "lease", "vehicle", "gold loan", "pawning", "interest", "rate", "rates", "apr", "instalment",
    "installment", "repay", "repayment", "emi", "card", "credit card", "debit card", "prepaid",
    "visa", "mastercard", "atm", "cheque", "check", "overdraft", "forex", "foreign exchange",
    "exchange rate", "currency", "usd", "lkr", "remittance", "remit", "transfer", "swift", "wire",
    "nrfc", "non-resident", "investment", "invest", "treasury", "bond", "treasury bill", "t-bill",
    "unit trust", "share", "stock", "guarantee", "trade finance", "letter of credit", "sme",
    "business banking", "corporate", "kyc", "open an account", "fee", "charge", "charges", "tariff",
    "branch", "online banking", "digital banking", "mobile banking", "salary", "fund", "money",
    "payment", "pay", "insurance", "bancassurance", "eligibility", "apply", "application", "document",
}

# Short semantic anchors describing the domain (embedded once, offline hashing embedder).
DOMAIN_ANCHORS = [
    "bank loans, mortgages and interest rates",
    "savings accounts and fixed deposit interest",
    "credit, debit and prepaid cards",
    "foreign exchange rates and money remittances",
    "opening a bank account and required documents",
    "business and corporate banking, trade finance",
    "investments, treasury bills and bonds",
]

SCOPE_GUARD = os.getenv("SCOPE_GUARD", "on").lower() in ("1", "true", "on", "yes")
SCOPE_THRESHOLD = float(os.getenv("SCOPE_THRESHOLD", "0.18"))
_ANCHOR_VECS: list | None = None


def _anchor_vecs():
    global _ANCHOR_VECS
    if _ANCHOR_VECS is None:
        from rag.embeddings import HashingEmbedder
        emb = HashingEmbedder()
        _ANCHOR_VECS = [(emb, emb.embed(a)) for a in DOMAIN_ANCHORS]
    return _ANCHOR_VECS


def in_scope(text: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means the question is outside the assistant's banking domain
    and must be rejected at the input rail WITHOUT calling the LLM or retrieval. Greetings and
    in-session follow-ups are handled upstream and never reach this check."""
    if not SCOPE_GUARD:
        return True, ""
    low = text.lower()
    if any(kw in low for kw in DOMAIN_KEYWORDS):   # fast lexical path
        return True, ""
    try:
        from rag.embeddings import HashingEmbedder, cosine
        qv = HashingEmbedder().embed(text)
        best = max((cosine(qv, v) for _, v in _anchor_vecs()), default=0.0)
        if best >= SCOPE_THRESHOLD:
            return True, ""
    except Exception:
        return True, ""   # never block on a guardrail failure
    return False, "out_of_scope"


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
