"""Admin-service API: Administrator-only enforcement + secret never returned + upload→index."""
import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("multipart")  # python-multipart, needed for Form/File endpoints


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("LLM_CONFIG_PERSIST", "false")
    import llm.config_store as cs
    cs.reset_config_store()
    # import the admin app fresh
    import importlib, sys
    sys.path.insert(0, "services/ai-admin-service")
    main = importlib.import_module("app.main")
    importlib.reload(main)
    from fastapi.testclient import TestClient
    return TestClient(main.app)


def _h(role):
    return {"Authorization": f"Bearer {role}"}


def test_requires_auth(client):
    assert client.get("/admin/llm").status_code == 401


def test_non_admin_forbidden(client):
    assert client.get("/admin/llm", headers=_h("analyst")).status_code == 403
    assert client.get("/admin/kb", headers=_h("viewer")).status_code == 403


def test_create_llm_never_returns_secret(client):
    body = {"provider": "gemini", "model_strong": "gemini-pro-latest",
            "model_fast": "gemini-flash-latest", "api_key": "LEAKME-123", "activate": True}
    r = client.post("/admin/llm", json=body, headers=_h("admin"))
    assert r.status_code == 201, r.text
    assert "LEAKME-123" not in r.text
    data = r.json()
    assert data["has_secret"] is True and "api_key" not in data and "secret" not in data
    # list also never leaks
    lr = client.get("/admin/llm", headers=_h("admin"))
    assert "LEAKME-123" not in lr.text
    assert lr.json()["configs"][0]["has_secret"] is True


def test_upload_and_index_progress(client):
    md = (b"---\ndoc_id: DOC-API-1\ntitle: API Test\naccess_level: internal\n---\n\n"
          b"# Scope\nOvertime approval requires manager sign-off.")
    r = client.post("/admin/documents/upload",
                    files={"file": ("x.md", md, "text/markdown")},
                    data={"doc_id": "DOC-API-1", "access_level": "internal", "title": "API Test"},
                    headers=_h("admin"))
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    jr = client.get(f"/admin/jobs/{job_id}", headers=_h("admin")).json()
    assert jr["stage"] == "done", jr
    assert jr["chunks"] >= 1
