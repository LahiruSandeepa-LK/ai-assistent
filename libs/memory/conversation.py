"""Conversation memory: history + rolling summary (every N turns) + semantic cache.
docs/05-memory.md, docs/14 §2-3."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from rag.embeddings import HashingEmbedder, cosine


def _jsonable_citations(citations: list) -> list:
    """Normalise citations to a list of plain dicts so the semantic cache is JSON-serialisable
    (Redis) and identical across the in-memory and Redis paths."""
    out = []
    for c in citations or []:
        if isinstance(c, dict):
            out.append(c)
        elif hasattr(c, "__dataclass_fields__"):
            from dataclasses import asdict
            out.append(asdict(c))
        else:
            out.append({"doc_id": str(c)})
    return out


VERBATIM_TURNS = int(os.getenv("VERBATIM_TURNS", "6"))
SUMMARIZE_EVERY = int(os.getenv("SUMMARIZE_EVERY_N_TURNS", "10"))
CACHE_THRESHOLD = float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.95"))


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    text: str
    ts: float = field(default_factory=time.time)


RELEVANT_TURNS_K = int(os.getenv("MEMORY_RELEVANT_K", "3"))
RELEVANT_TURNS_THRESHOLD = float(os.getenv("MEMORY_RELEVANT_THRESHOLD", "0.35"))
HISTORY_SESSIONS = int(os.getenv("HISTORY_SESSIONS", "3"))


@dataclass
class Session:
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    summary: str = ""
    user_query_count: int = 0
    user_id: str = ""


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

    # ---- semantic cache (Redis when available for cross-replica sharing; else in-memory) ----
    def _cache_entries(self, session_id: str):
        try:
            from .redis_client import get_redis

            r = get_redis()
            if r is not None:
                import json

                out = []
                for raw in r.lrange(f"cache:{session_id}", 0, -1):
                    d = json.loads(raw)
                    out.append((d["v"], d["a"], d["c"]))
                return out
        except Exception:
            pass
        return self._cache.get(session_id, [])

    def cache_lookup(self, session_id: str, query: str):
        qv = self._embedder.embed(query)
        best = None
        best_sim = 0.0
        for vec, answer, citations in self._cache_entries(session_id):
            sim = cosine(qv, vec)
            if sim > best_sim:
                best_sim, best = sim, (answer, citations)
        if best and best_sim >= CACHE_THRESHOLD:
            return best
        return None

    def cache_store(self, session_id: str, query: str, answer: str, citations: list) -> None:
        vec = self._embedder.embed(query)
        cites = _jsonable_citations(citations)  # store JSON-safe in BOTH paths for consistency
        try:
            from .redis_client import get_redis

            r = get_redis()
            if r is not None:
                import json

                r.rpush(f"cache:{session_id}", json.dumps({"v": vec, "a": answer, "c": cites}))
                r.expire(f"cache:{session_id}", 7 * 24 * 3600)
                return
        except Exception:
            pass
        self._cache.setdefault(session_id, []).append((vec, answer, cites))

    # ---- memory-as-RAG: only the turns in THIS session that are relevant to the query ----
    def relevant_turns(self, session_id: str, query: str, k: int = RELEVANT_TURNS_K,
                       threshold: float = RELEVANT_TURNS_THRESHOLD) -> list[tuple[str, str]]:
        """Return up to k prior turns from this session semantically relevant to `query`. Used
        instead of dumping the whole history into the prompt. Session-scoped only — never crosses
        sessions, so a new session starts with nothing to retrieve."""
        s = self.get(session_id)
        if not s.turns:
            return []
        qv = self._embedder.embed(query)
        scored = [(cosine(qv, self._embedder.embed(t.text)), t) for t in s.turns]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(t.role, t.text) for sim, t in scored[:k] if sim >= threshold]

    # ---- per-user session history (for UI display only; never fed to the agent) ----
    def list_user_sessions(self, user_id: str, limit: int = HISTORY_SESSIONS,
                           exclude_session: str = "") -> list[dict]:
        rows = []
        for sid, s in self._sessions.items():
            if s.user_id != user_id or sid == exclude_session or not s.turns:
                continue
            first = next((t for t in s.turns if t.role == "user"), s.turns[0])
            rows.append({
                "session_id": sid,
                "title": (first.text[:60] + ("…" if len(first.text) > 60 else "")),
                "started_at": s.turns[0].ts,
                "turns": [(t.role, t.text) for t in s.turns],
            })
        rows.sort(key=lambda r: r["started_at"], reverse=True)
        return rows[:limit]

    # ---- turns + summarization cadence ----
    def add_user(self, session_id: str, text: str, user_id: str = "") -> None:
        s = self.get(session_id)
        if user_id:
            s.user_id = user_id
        s.turns.append(Turn("user", text))
        s.user_query_count += 1

    def add_assistant(self, session_id: str, text: str, user_id: str = "") -> None:
        s = self.get(session_id)
        if user_id:
            s.user_id = user_id
        s.turns.append(Turn("assistant", text))

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
        try:
            from db.engine import pg_enabled

            if pg_enabled():
                from db.stores import PgConversationStore

                _STORE = PgConversationStore()
                return _STORE
        except Exception:
            pass  # fall back to in-memory on any DB/driver error
        _STORE = ConversationStore()
    return _STORE


def reset_conversation_store() -> None:
    global _STORE
    _STORE = None
