"""Postgres-backed implementations of the conversation and ingest-job stores. These subclass the
in-memory stores and override persistence, so behaviour is identical and the semantic cache stays
in-process (vectors). Selected automatically when POSTGRES_DSN is set. docs/05, docs/13.
"""
from __future__ import annotations

import time

from sqlalchemy import delete, func, select

from memory.conversation import ConversationStore, Session, Turn, VERBATIM_TURNS, SUMMARIZE_EVERY
from admin.jobs import IngestJob, JobStore, STAGE_PROGRESS
from .engine import (ConversationSummary, ConversationTurn, Document, IngestJobRow,
                     get_sessionmaker, init_db)


class PgConversationStore(ConversationStore):
    """History + rolling summary persisted in Postgres; semantic cache stays in-memory."""

    def __init__(self):
        super().__init__()
        init_db()
        self._sm = get_sessionmaker()

    def add_user(self, session_id: str, text: str) -> None:
        with self._sm() as s:
            s.add(ConversationTurn(session_id=session_id, role="user", text=text, ts=time.time()))
            s.commit()

    def add_assistant(self, session_id: str, text: str) -> None:
        with self._sm() as s:
            s.add(ConversationTurn(session_id=session_id, role="assistant", text=text, ts=time.time()))
            s.commit()

    def recent_turns(self, session_id: str) -> list[Turn]:
        with self._sm() as s:
            rows = s.execute(
                select(ConversationTurn).where(ConversationTurn.session_id == session_id)
                .order_by(ConversationTurn.id.desc()).limit(VERBATIM_TURNS)).scalars().all()
        return [Turn(role=r.role, text=r.text, ts=r.ts) for r in reversed(rows)]

    def _summary(self, session_id: str) -> str:
        with self._sm() as s:
            row = s.get(ConversationSummary, session_id)
            return row.summary if row else ""

    def context_bundle(self, session_id: str) -> dict:
        return {"summary": self._summary(session_id),
                "recent_turns": [(t.role, t.text) for t in self.recent_turns(session_id)]}

    def _user_turn_count(self, session_id: str) -> int:
        with self._sm() as s:
            return int(s.execute(
                select(func.count()).select_from(ConversationTurn)
                .where(ConversationTurn.session_id == session_id,
                       ConversationTurn.role == "user")).scalar() or 0)

    def due_for_summary(self, session_id: str) -> bool:
        n = self._user_turn_count(session_id)
        return n > 0 and n % SUMMARIZE_EVERY == 0

    def set_summary(self, session_id: str, summary: str) -> None:
        with self._sm() as s:
            row = s.get(ConversationSummary, session_id)
            if row:
                row.summary = summary
            else:
                s.add(ConversationSummary(session_id=session_id, summary=summary))
            s.commit()

    def older_block(self, session_id: str) -> str:
        with self._sm() as s:
            rows = s.execute(
                select(ConversationTurn).where(ConversationTurn.session_id == session_id)
                .order_by(ConversationTurn.id.asc())).scalars().all()
        older = rows[:-VERBATIM_TURNS] if len(rows) > VERBATIM_TURNS else []
        return "\n".join(f"{r.role}: {r.text}" for r in older)


class PgJobStore(JobStore):
    """Ingest jobs persisted in Postgres so progress is visible across replicas; also records a
    document-registry row when a job completes."""

    def __init__(self):
        super().__init__()
        init_db()
        self._sm = get_sessionmaker()

    def _row_to_job(self, r: IngestJobRow) -> IngestJob:
        return IngestJob(id=r.id, doc_id=r.doc_id, filename=r.filename, stage=r.stage,
                         progress=r.progress, chunks=r.chunks, message=r.message, error=r.error,
                         created_at=r.created_at, updated_at=r.updated_at)

    def create(self, doc_id: str, filename: str) -> IngestJob:
        job = super().create(doc_id, filename)  # gives us an id + timestamps
        with self._sm() as s:
            s.add(IngestJobRow(id=job.id, doc_id=doc_id, filename=filename, stage=job.stage,
                               progress=job.progress, created_at=job.created_at,
                               updated_at=job.updated_at))
            s.commit()
        return job

    def update(self, job_id: str, *, stage=None, progress=None, chunks=None, message=None, error=None):
        with self._sm() as s:
            r = s.get(IngestJobRow, job_id)
            if not r:
                return
            if stage is not None:
                r.stage = stage
                r.progress = max(r.progress, STAGE_PROGRESS.get(stage, r.progress))
            if progress is not None:
                r.progress = max(0, min(100, progress))
            if chunks is not None:
                r.chunks = chunks
            if message is not None:
                r.message = message
            if error is not None:
                r.error = error
            r.updated_at = time.time()
            # on completion, upsert the document registry
            if r.stage == "done":
                doc = s.get(Document, r.doc_id)
                if doc:
                    doc.chunks = r.chunks
                else:
                    s.add(Document(doc_id=r.doc_id, title=r.filename, chunks=r.chunks,
                                   created_at=time.time()))
            s.commit()

    def get(self, job_id: str) -> IngestJob | None:
        with self._sm() as s:
            r = s.get(IngestJobRow, job_id)
            return self._row_to_job(r) if r else None

    def list(self) -> list[IngestJob]:
        with self._sm() as s:
            rows = s.execute(select(IngestJobRow).order_by(IngestJobRow.created_at.desc())).scalars().all()
            return [self._row_to_job(r) for r in rows]
