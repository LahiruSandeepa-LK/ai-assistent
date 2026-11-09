"""Shared Redis connection. Returns a client when REDIS_URL is set and reachable, else None so
callers fall back to in-memory. One pooled client per process. docs/14, ADR-008/010."""
from __future__ import annotations

import os

_CLIENT = None
_TRIED = False


def get_redis():
    """Return a redis client (decode_responses=True) or None if unavailable."""
    global _CLIENT, _TRIED
    if _TRIED:
        return _CLIENT
    _TRIED = True
    url = os.getenv("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis  # pip install redis

        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        _CLIENT = client
    except Exception:
        _CLIENT = None
    return _CLIENT


def reset_redis() -> None:
    """Test hook: drop the cached client so the next get_redis() reconnects."""
    global _CLIENT, _TRIED
    _CLIENT, _TRIED = None, False
