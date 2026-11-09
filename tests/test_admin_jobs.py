"""Admin ingestion jobs: staged progress + end-to-end upload runner (md/html/xlsx)."""
import os

from admin.jobs import JobStore, STAGE_PROGRESS
from admin.ingest_runner import run_ingest_job, _to_text
from admin.jobs import get_job_store
from rag.store import get_index


def test_job_progresses_through_stages():
    s = JobStore()
    job = s.create("DOC-1", "a.md")
    assert job.stage == "queued"
    for stg in ("extracting", "chunking", "indexing", "done"):
        s.update(job.id, stage=stg)
    j = s.get(job.id)
    assert j.stage == "done" and j.progress == 100


def test_progress_is_monotonic_non_decreasing():
    s = JobStore()
    job = s.create("DOC-2", "b.md")
    s.update(job.id, progress=60)
    s.update(job.id, stage="queued")  # lower nominal stage must not pull progress back
    assert s.get(job.id).progress == 60


def test_to_text_markdown():
    text, fmt = _to_text(b"# Title\n\nHello body", "note.md")
    assert "Hello body" in text and fmt in ("md", "text")


def test_to_text_html_strips_tags():
    text, fmt = _to_text(b"<h1>H</h1><p>Visible text</p>", "page.html")
    assert "Visible text" in text and "<p>" not in text and fmt == "html"


def test_run_ingest_job_indexes_markdown():
    jobs = get_job_store()
    job = jobs.create("DOC-INGEST-TEST", "policy.md")
    md = ("---\ndoc_id: DOC-INGEST-TEST\ntitle: Test Policy\naccess_level: internal\n---\n\n"
          "# Overview\nThis policy covers wire transfer limits and approvals.")
    run_ingest_job(job.id, md.encode(), "policy.md", "DOC-INGEST-TEST")
    done = jobs.get(job.id)
    assert done.stage == "done", done.error
    assert done.chunks >= 1
    # the content is now searchable in the index
    idx = get_index()
    assert any(c.source.doc_id == "DOC-INGEST-TEST" for c in idx.chunks.values())


def test_shared_index_file_propagates_across_instances(monkeypatch, tmp_path):
    """A doc indexed by one process (admin-service) must be searchable by another (chat API)."""
    monkeypatch.setenv("INDEX_PATH", str(tmp_path / "index.json"))
    import asyncio
    from rag.store import KnowledgeIndex
    from rag.ingest import ingest_text
    from contracts.models import RetrievalRequest

    writer = KnowledgeIndex()  # stands in for ai-admin-service
    ingest_text(writer,
                "---\ndoc_id: SHARED-1\ntitle: Shared Policy\naccess_level: public\n---\n\n"
                "# Limits\nThe daily wire transfer limit is 50000 dollars.",
                doc_id_fallback="SHARED-1")

    reader = KnowledgeIndex()  # separate instance = separate process reading the shared file
    res = asyncio.run(reader.search(
        RetrievalRequest(query="daily wire transfer limit", top_k=3, access_level_max="public")))
    assert any(c.source.doc_id == "SHARED-1" for c in res.chunks)


def test_run_ingest_job_xlsx_if_openpyxl_present():
    import importlib.util
    if importlib.util.find_spec("openpyxl") is None:
        return  # optional dependency not installed; skip silently
    from openpyxl import Workbook
    import io
    wb = Workbook(); ws = wb.active; ws.title = "Rates"
    ws.append(["Product", "Rate"]); ws.append(["Savings", "3.5%"])
    buf = io.BytesIO(); wb.save(buf)
    jobs = get_job_store()
    job = jobs.create("DOC-XLSX", "rates.xlsx")
    run_ingest_job(job.id, buf.getvalue(), "rates.xlsx", "DOC-XLSX")
    j = jobs.get(job.id)
    assert j.stage == "done", j.error
    assert any("Savings" in c.text for c in get_index().chunks.values())
