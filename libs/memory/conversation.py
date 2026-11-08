"""Conversation memory: history + rolling summary (every N turns) + semantic cache.
docs/05-memory.md, docs/14 §2-3."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from rag.embeddings import HashingEmbedder, cosine

VERBATIM_TURNS = int(os.getenv("VERBATIM_TURNS", "6"))
SUMMARIZE_EVERY = int(os.getenv("SUMMARIZE_EVERY_N_TURNS", "10"))
CACHE_THRESHOLD = float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.95"))


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    text: str
    ts: float = field(default_factory=time.time)


@dataclass
class Session:
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    summary: str = ""
    user_query_count: int = 0


class ConversationStore:
    """In-memory sessions + a per-session semantic cache of (query_vec, answer)."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._cache: dict[str, list[tuple[list[float], str, list]]] = {}
        self._embedder = HashingEmbedder()

    def get(self, session_id: str) -> Session:
        return self._sessions.setdefault(session_id, Session(session_id=session_id))

    def recent_turns(self, session_id: str) -> list[Turn]:
        return self.get(session_id).turns[-VERBATIM_TURNS:]

    def context_bundle(self, session_id: str) -> dict:
        s = self.get(session_id)
        return {
            "summary": s.summary,
            "recent_turns": [(t.role, t.text) for t in self.recent_turns(session_id)],
        }

    # ---- cache ----
    def cache_lookup(self, session_id: str, query: str):
        qv = self._embedder.embed(query)
        best = None
        best_sim = 0.0
        for vec, answer, citations in self._cache.get(session_id, []):
            sim = cosine(qv, vec)
            if sim > best_sim:
                best_sim, best = sim, (answer, citations)
        if best and best_sim >= CACHE_THRESHOLD:
            return best
        return None

    def cache_store(self, session_id: str, query: str, answer: str, citations: list) -> None:
        self._cache.setdefault(session_id, []).append((self._embedder.embed(query), answer, citations))

    # ---- turns + summarization cadence ----
    def add_user(self, session_id: str, text: str) -> None:
        s = self.get(session_id)
        s.turns.append(Turn("user", text))
        s.user_query_count += 1

    def add_assistant(self, session_id: str, text: str) -> None:
        self.get(session_id).turns.append(Turn("assistant", text))

    def due_for_summary(self, session_id: str) -> bool:
        s = self.get(session_id)
        return s.user_query_count > 0 and s.user_query_count % SUMMARIZE_EVERY == 0

    def set_summary(self, session_id: str, summary: str) -> None:
        self.get(session_id).summary = summary

    def older_block(self, session_id: str) -> str:
        """Text of turns older than the verbatim window — fed to the summarizer."""
        s = self.get(session_id)
        older = s.turns[:-VERBATIM_TURNS] if len(s.turns) > VERBATIM_TURNS else []
        return "\n".join(f"{t.role}: {t.text}" for t in older)


_STORE: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    global _STORE
    if _STORE is None:
        _STORE = ConversationStore()
    return _STORE
