"""Ingestion job tracking for the admin console. An upload becomes a job that moves through
stages (queued -> extracting -> chunking -> indexing -> done|failed); the admin UI polls the
job for a live progress bar. In-memory store (per-process) — fine for the POC; a real
deployment would persist jobs in Postgres and stream progress over SSE/WebSocket. docs/09, docs/13.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field

STAGES = ("queued", "extracting", "chunking", "indexing", "done", "failed")
# nominal progress milestones per stage, so the bar advances even before chunk counts are known
STAGE_PROGRESS = {"queued": 5, "extracting": 30, "chunking": 55, "indexing": 80, "done": 100, "failed": 100}


@dataclass
class IngestJob:
    id: str
    doc_id: str
    filename: str
    stage: str = "queued"
    progress: int = 0
    chunks: int = 0
    message: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class JobStore:
    def __init__(self):
        self._jobs: dict[str, IngestJob] = {}
        self._lock = threading.RLock()

    def create(self, doc_id: str, filename: str) -> IngestJob:
        jid = uuid.uuid4().hex[:12]
        job = IngestJob(id=jid, doc_id=doc_id, filename=filename)
        with self._lock:
            self._jobs[jid] = job
        return job

    def update(self, job_id: str, *, stage: str | None = None, progress: int | None = None,
               chunks: int | None = None, message: str | None = None, error: str | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if stage is not None:
                job.stage = stage
                job.progress = max(job.progress, STAGE_PROGRESS.get(stage, job.progress))
            if progress is not None:
                job.progress = max(0, min(100, progress))
            if chunks is not None:
                job.chunks = chunks
            if message is not None:
                job.message = message
            if error is not None:
                job.error = error
            job.updated_at = time.time()

    def get(self, job_id: str) -> IngestJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[IngestJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)


_STORE: JobStore | None = None


def get_job_store() -> JobStore:
    global _STORE
    if _STORE is None:
        try:
            from db.engine import pg_enabled

            if pg_enabled():
                from db.stores import PgJobStore

                _STORE = PgJobStore()
                return _STORE
        except Exception:
            pass  # fall back to in-memory on any DB/driver error
        _STORE = JobStore()
    return _STORE


def reset_job_store() -> None:
    global _STORE
    _STORE = None
