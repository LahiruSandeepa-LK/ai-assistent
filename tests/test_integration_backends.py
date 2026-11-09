"""Tests for the real-backend integration layer.

Pure tests (HTTP deserialisation, DSN normalisation, selector fallback) always run. The live
Redis/Postgres tests run only when REDIS_URL / POSTGRES_DSN point at a reachable server, so the
default offline suite stays green.
"""
import os

import pytest


# ---- pure: HTTP client deserialisation ----
def test_chunk_from_json_roundtrip():
    from contracts.models import Chunk, Source, to_jsonable
    from clients.services import chunk_from_json

    c = Chunk(chunk_id="x1", text="hello", source=Source(doc_id="D1", title="T", section="S", url="u"),
              metadata={"access_level": "public"}, score=0.8)
    back = chunk_from_json(to_jsonable(c))
    assert back.chunk_id == "x1" and back.source.doc_id == "D1"
    assert back.metadata["access_level"] == "public" and back.score == 0.8


# ---- pure: Postgres DSN normalisation always targets psycopg2 ----
def test_sync_dsn_normalisation():
    from db.engine import _sync_dsn
    assert _sync_dsn("postgresql+asyncpg://a:b@h:5432/d") == "postgresql+psycopg2://a:b@h:5432/d"
    assert _sync_dsn("postgresql://a:b@h:5432/d") == "postgresql+psycopg2://a:b@h:5432/d"
    assert _sync_dsn("postgres://a:b@h/d") == "postgresql+psycopg2://a:b@h/d"


# ---- pure: selectors fall back to in-memory without env ----
def test_selectors_fall_back_in_memory(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    from memory.redis_client import reset_redis
    from memory.usage import get_usage_store, reset_usage_store, UsageStore
    from memory.conversation import get_conversation_store, reset_conversation_store, ConversationStore
    from admin.jobs import get_job_store, reset_job_store, JobStore
    reset_redis(); reset_usage_store(); reset_conversation_store(); reset_job_store()
    assert type(get_usage_store()) is UsageStore
    assert type(get_conversation_store()) is ConversationStore
    assert type(get_job_store()) is JobStore


# ---- live: Redis (skips if unreachable) ----
def _redis_ok() -> bool:
    url = os.getenv("REDIS_URL")
    if not url:
        return False
    try:
        import redis
        redis.Redis.from_url(url, socket_connect_timeout=1).ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _redis_ok(), reason="no reachable REDIS_URL")
def test_redis_usage_store_live():
    from memory.redis_client import reset_redis
    from memory.usage import get_usage_store, reset_usage_store, RedisUsageStore
    reset_redis(); reset_usage_store()
    s = get_usage_store()
    assert isinstance(s, RedisUsageStore)
    uid = "pytest-redis-user"
    before = s.get(uid, "Analyst").used
    s.record(uid, 50)
    assert s.get(uid, "Analyst").used == before + 50


# ---- live: Postgres (skips if unreachable) ----
def _pg_ok() -> bool:
    dsn = os.getenv("POSTGRES_DSN")
    if not dsn:
        return False
    try:
        from db.engine import get_engine, reset_engine
        reset_engine()
        get_engine().connect().close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _pg_ok(), reason="no reachable POSTGRES_DSN")
def test_pg_conversation_and_jobs_live():
    from memory.conversation import get_conversation_store, reset_conversation_store
    from admin.jobs import get_job_store, reset_job_store
    from db.stores import PgConversationStore, PgJobStore
    reset_conversation_store(); reset_job_store()
    cs = get_conversation_store(); js = get_job_store()
    assert isinstance(cs, PgConversationStore) and isinstance(js, PgJobStore)
    sid = "pytest-pg-session"
    cs.add_user(sid, "hello"); cs.add_assistant(sid, "hi")
    turns = cs.context_bundle(sid)["recent_turns"]
    assert ("user", "hello") in turns
    j = js.create("PYTEST-DOC", "f.md"); js.update(j.id, stage="done", chunks=3)
    assert js.get(j.id).stage == "done" and js.get(j.id).chunks == 3
