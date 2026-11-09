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
