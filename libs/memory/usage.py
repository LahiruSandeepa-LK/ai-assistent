"""Per-user token budget. In-memory offline; Redis when REDIS_URL is set.
docs/14 §1, ADR-010. Distinct from rate limiting."""
from __future__ import annotations

import os
import time

from contracts.models import Usage

ROLE_LIMITS = {
    "Viewer": int(os.getenv("TOKEN_BUDGET_VIEWER", "200000")),
    "Analyst": int(os.getenv("TOKEN_BUDGET_ANALYST", "1000000")),
    "Administrator": int(os.getenv("TOKEN_BUDGET_ADMIN", "5000000")),
}
PERIOD = os.getenv("TOKEN_BUDGET_PERIOD", "monthly")


def _period_key() -> str:
    t = time.gmtime()
    return f"{t.tm_year}-{t.tm_mon:02d}" if PERIOD == "monthly" else f"{t.tm_year}-{t.tm_yday}"


def _reset_at() -> str:
    t = time.gmtime()
    if PERIOD == "monthly":
        y, m = (t.tm_year + 1, 1) if t.tm_mon == 12 else (t.tm_year, t.tm_mon + 1)
        return f"{y}-{m:02d}-01"
    return "next day (UTC)"


def _period_ttl() -> int:
    # seconds until the current budget window ends (used to expire Redis counters)
    return 40 * 24 * 3600 if PERIOD == "monthly" else 2 * 24 * 3600


class UsageStore:
    """Token-budget accounting. In-memory default."""

    def __init__(self):
        self._used: dict[str, int] = {}

    def _key(self, user_id: str) -> str:
        return f"usage:{user_id}:{_period_key()}"

    def get(self, user_id: str, role: str) -> Usage:
        limit = ROLE_LIMITS.get(role, ROLE_LIMITS["Viewer"])
        used = self._used.get(self._key(user_id), 0)
        return Usage(user_id=user_id, limit=limit, used=used, reset_at=_reset_at())

    def check(self, user_id: str, role: str) -> Usage:
        """Return current usage; caller rejects if remaining <= 0 (pre-flight)."""
        return self.get(user_id, role)

    def record(self, user_id: str, tokens: int) -> None:
        """Post-flight metering: add actual tokens used."""
        k = self._key(user_id)
        self._used[k] = self._used.get(k, 0) + max(0, int(tokens))


class RedisUsageStore(UsageStore):
    """Token budget backed by Redis — atomic INCRBY, shared across all service replicas, with the
    counter auto-expiring at period end. Falls back to in-memory semantics on any Redis error."""

    def __init__(self, client):
        super().__init__()
        self._r = client

    def get(self, user_id: str, role: str) -> Usage:
        limit = ROLE_LIMITS.get(role, ROLE_LIMITS["Viewer"])
        try:
            used = int(self._r.get(self._key(user_id)) or 0)
        except Exception:
            used = self._used.get(self._key(user_id), 0)
        return Usage(user_id=user_id, limit=limit, used=used, reset_at=_reset_at())

    def record(self, user_id: str, tokens: int) -> None:
        k = self._key(user_id)
        try:
            new = self._r.incrby(k, max(0, int(tokens)))
            if new == max(0, int(tokens)):   # first write this window -> set TTL
                self._r.expire(k, _period_ttl())
        except Exception:
            super().record(user_id, tokens)


_STORE: UsageStore | None = None


def get_usage_store() -> UsageStore:
    global _STORE
    if _STORE is None:
        from .redis_client import get_redis

        client = get_redis()
        _STORE = RedisUsageStore(client) if client is not None else UsageStore()
    return _STORE


def reset_usage_store() -> None:
    global _STORE
    _STORE = None


# ---------------------------------------------------------------------------
# Per-SESSION token accounting + cap. Separate from the per-user budget above:
# one chat session is capped (default 100k tokens) and the user is asked to start
# a new chat when it fills up. Configurable via SESSION_TOKEN_CAP. docs/14 §3.
# ---------------------------------------------------------------------------
def session_cap() -> int:
    """Max tokens per chat session. 0 disables the cap. Read live so it's env-configurable."""
    try:
        return int(os.getenv("SESSION_TOKEN_CAP", "100000"))
    except ValueError:
        return 100000


def _session_ttl() -> int:
    try:
        return int(os.getenv("SESSION_TOKEN_TTL", str(24 * 3600)))
    except ValueError:
        return 24 * 3600


class SessionUsageStore:
    """Cumulative tokens for a single chat session. In-memory default."""

    def __init__(self):
        self._used: dict[str, int] = {}

    def _key(self, session_id: str) -> str:
        return f"session_tokens:{session_id}"

    def get(self, session_id: str) -> int:
        return self._used.get(self._key(session_id), 0)

    def record(self, session_id: str, tokens: int) -> None:
        k = self._key(session_id)
        self._used[k] = self._used.get(k, 0) + max(0, int(tokens))

    def remaining(self, session_id: str) -> int:
        cap = session_cap()
        return max(0, cap - self.get(session_id)) if cap > 0 else 1_000_000_000

    def over_cap(self, session_id: str) -> bool:
        cap = session_cap()
        return cap > 0 and self.get(session_id) >= cap


class RedisSessionUsageStore(SessionUsageStore):
    """Session token counter backed by Redis (atomic INCRBY, shared across replicas, TTL-expired)."""

    def __init__(self, client):
        super().__init__()
        self._r = client

    def get(self, session_id: str) -> int:
        try:
            return int(self._r.get(self._key(session_id)) or 0)
        except Exception:
            return super().get(session_id)

    def record(self, session_id: str, tokens: int) -> None:
        k = self._key(session_id)
        try:
            new = self._r.incrby(k, max(0, int(tokens)))
            if new == max(0, int(tokens)):   # first write for this session -> set TTL
                self._r.expire(k, _session_ttl())
        except Exception:
            super().record(session_id, tokens)


_SESSION_STORE: SessionUsageStore | None = None


def get_session_usage() -> SessionUsageStore:
    global _SESSION_STORE
    if _SESSION_STORE is None:
        from .redis_client import get_redis

        client = get_redis()
        _SESSION_STORE = RedisSessionUsageStore(client) if client is not None else SessionUsageStore()
    return _SESSION_STORE


def reset_session_usage() -> None:
    global _SESSION_STORE
    _SESSION_STORE = None
