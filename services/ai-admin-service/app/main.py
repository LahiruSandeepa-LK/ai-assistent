"""ai-admin-service — admin backend (Administrator-only): document management with live
indexing progress + runtime LLM configuration. docs/13, ADR-009, ADR-011.

Security:
  * Every endpoint requires a bearer token that resolves to the Administrator role (PEP at the
    edge; the agent PEP still guards tools downstream).
  * LLM API keys are WRITE-ONLY: accepted on create, never returned by any endpoint.
"""
from __future__ import annotations

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from contracts.errors import AuthzError
from contracts.models import UserContext
from authz.identity import resolve_user
from rag.ingest import ingest_text
from rag.store import get_index
from admin.jobs import get_job_store
from admin.ingest_runner import run_ingest_job
from llm.config_store import get_config_store
from llm.gateway import reset_gateway

app = FastAPI(title="ai-admin-service")


# ---- auth: Administrator only ----
def require_admin(authorization: str | None = Header(default=None)) -> UserContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        user = resolve_user(token, session_id="admin")
    except AuthzError as e:
        raise HTTPException(401, e.message)
    if "Administrator" not in user.roles:
        raise HTTPException(403, "administrator role required")
    return user


@app.get("/health")
async def health():
    idx = get_index()
    return {"status": "ok", "documents": len({c.source.doc_id for c in idx.chunks.values()}),
            "chunks": len(idx.chunks)}


# ---- document management ----
class DocUpload(BaseModel):
    doc_id: str
    content: str


@app.post("/admin/documents")
async def upload_text(body: DocUpload, _: UserContext = Depends(require_admin)):
    n = ingest_text(get_index(), body.content, doc_id_fallback=body.doc_id)
    return {"doc_id": body.doc_id, "status": "indexed", "chunks": n}


@app.post("/admin/documents/upload")
async def upload_file(background: BackgroundTasks, file: UploadFile = File(...),
                      doc_id: str = Form(...), access_level: str = Form("internal"),
                      title: str = Form(""), _: UserContext = Depends(require_admin)):
    """Accept a pdf/docx/xlsx/md/txt/html file; index it in the background with progress."""
    data = await file.read()
    job = get_job_store().create(doc_id=doc_id, filename=file.filename or doc_id)
    background.add_task(run_ingest_job, job.id, data, file.filename or doc_id, doc_id,
                        access_level, title)
    return {"job_id": job.id, "doc_id": doc_id, "filename": file.filename, "stage": job.stage}


@app.get("/admin/jobs/{job_id}")
async def job_status(job_id: str, _: UserContext = Depends(require_admin)):
    job = get_job_store().get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job.to_dict()


@app.get("/admin/jobs")
async def list_jobs(_: UserContext = Depends(require_admin)):
    return {"jobs": [j.to_dict() for j in get_job_store().list()]}


@app.delete("/admin/documents/{doc_id}")
async def delete_doc(doc_id: str, _: UserContext = Depends(require_admin)):
    n = get_index().delete_doc(doc_id)
    return {"doc_id": doc_id, "status": "deleted", "removed": n}


@app.get("/admin/kb")
async def kb(_: UserContext = Depends(require_admin)):
    idx = get_index()
    docs: dict[str, int] = {}
    for c in idx.chunks.values():
        docs[c.source.doc_id] = docs.get(c.source.doc_id, 0) + 1
    return {"documents": docs}


# ---- LLM configuration (create-only; secret write-only) ----
class LLMConfigIn(BaseModel):
    provider: str                 # gemini | anthropic | openai | mock
    model_strong: str = ""
    model_fast: str = ""
    label: str = ""
    base_url: str = ""
    api_key: str = ""             # WRITE-ONLY — stored, never returned
    activate: bool = True


@app.post("/admin/llm", status_code=201)
async def create_llm(body: LLMConfigIn, _: UserContext = Depends(require_admin)):
    try:
        cfg = get_config_store().create(
            body.provider, body.model_strong, body.model_fast,
            secret=body.api_key, label=body.label, base_url=body.base_url, activate=body.activate)
    except ValueError as e:
        raise HTTPException(400, str(e))
    reset_gateway()
    # NOTE: asdict carries has_secret (bool) but NOT the secret itself.
    return _public(cfg)


@app.get("/admin/llm")
async def list_llm(_: UserContext = Depends(require_admin)):
    return {"configs": [_public(c) for c in get_config_store().list()]}


@app.post("/admin/llm/{config_id}/activate")
async def activate_llm(config_id: str, _: UserContext = Depends(require_admin)):
    try:
        cfg = get_config_store().activate(config_id)
    except KeyError:
        raise HTTPException(404, "config not found")
    reset_gateway()
    return _public(cfg)


@app.delete("/admin/llm/{config_id}")
async def delete_llm(config_id: str, _: UserContext = Depends(require_admin)):
    ok = get_config_store().delete(config_id)
    reset_gateway()
    return {"id": config_id, "deleted": ok}


def _public(cfg) -> dict:
    """Serialise a config for the API — guarantees no secret leaks out."""
    return {
        "id": cfg.id, "provider": cfg.provider, "model_strong": cfg.model_strong,
        "model_fast": cfg.model_fast, "label": cfg.label, "base_url": cfg.base_url,
        "has_secret": cfg.has_secret, "active": cfg.active, "created_at": cfg.created_at,
    }
