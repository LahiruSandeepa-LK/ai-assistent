"""Postgres engine + schema. Sync SQLAlchemy 2.0 (psycopg2); used by the conversation, jobs and
document stores when POSTGRES_DSN is set. In-memory stores are the offline default. docs/13.
"""
from __future__ import annotations

import os

from sqlalchemy import String, Integer, Float, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    ts: Mapped[float] = mapped_column(Float)


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    summary: Mapped[str] = mapped_column(Text, default="")


class Document(Base):
    __tablename__ = "documents"
    doc_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    access_level: Mapped[str] = mapped_column(String(32), default="internal")
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float, default=0.0)


class IngestJobRow(Base):
    __tablename__ = "ingest_jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(128))
    filename: Mapped[str] = mapped_column(String(512))
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[float] = mapped_column(Float, default=0.0)


def dsn() -> str:
    return os.getenv("POSTGRES_DSN", "")


def _sync_dsn(d: str) -> str:
    # these stores are sync; accept an asyncpg/psycopg DSN but always drive it with psycopg2
    d = d.replace("+asyncpg", "").replace("+psycopg2", "").replace("+psycopg", "")
    if d.startswith("postgresql://"):
        d = d.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif d.startswith("postgres://"):
        d = d.replace("postgres://", "postgresql+psycopg2://", 1)
    return d


_ENGINE = None
_SESSION = None


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(_sync_dsn(dsn()), pool_pre_ping=True, future=True)
    return _ENGINE


def get_sessionmaker():
    global _SESSION
    if _SESSION is None:
        _SESSION = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SESSION


def init_db() -> None:
    """Create tables if absent. Safe to call on every startup."""
    Base.metadata.create_all(get_engine())


def pg_enabled() -> bool:
    return bool(dsn())


def reset_engine() -> None:
    global _ENGINE, _SESSION
    _ENGINE, _SESSION = None, None
