"""Tests for the real-backend wiring (Pinecone selection + Keycloak role mapping).
These run offline: no live Pinecone or Keycloak needed. The live adapters themselves are
exercised only when the matching env + packages are present (importorskip)."""
import os

import pytest

from rag.vectorstore import InMemoryVectorStore, VectorRecord, get_vector_store
from authz import identity


def test_get_vector_store_defaults_to_inmemory(monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    assert isinstance(get_vector_store(), InMemoryVectorStore)


def test_get_vector_store_falls_back_when_pinecone_missing(monkeypatch):
    # Key set but the pinecone package absent -> must degrade, not crash.
    monkeypatch.setenv("PINECONE_API_KEY", "x")
    if _pkg("pinecone"):
        pytest.skip("pinecone installed; fallback path not exercised")
    assert isinstance(get_vector_store(), InMemoryVectorStore)


def test_inmemory_store_roundtrip():
    s = InMemoryVectorStore()
    s.upsert([
        VectorRecord("c1", [1.0, 0.0], {"doc_id": "D1"}),
        VectorRecord("c2", [0.0, 1.0], {"doc_id": "D2"}),
    ])
    assert len(s) == 2
    top = s.query([1.0, 0.0], top_k=1)
    assert top[0][0] == "c1"
    assert s.delete("D1") == 1 and len(s) == 1


def test_pinecone_adapter_importable_if_installed():
    pytest.importorskip("pinecone")
    from rag.vectorstore_pinecone import PineconeVectorStore  # noqa: F401


# ---- Keycloak role mapping ----

def test_extract_roles_from_realm_and_resource(monkeypatch):
    monkeypatch.delenv("KEYCLOAK_ROLE_MAP", raising=False)
    claims = {
        "realm_access": {"roles": ["offline_access", "Analyst"]},
        "resource_access": {"ai-assistant": {"roles": ["Administrator"]}},
    }
    roles = identity.extract_roles(claims, "ai-assistant")
    assert roles == ["Analyst", "Administrator"]


def test_extract_roles_case_insensitive_and_drops_unknown(monkeypatch):
    monkeypatch.delenv("KEYCLOAK_ROLE_MAP", raising=False)
    claims = {"realm_access": {"roles": ["viewer", "random-role"]}}
    assert identity.extract_roles(claims) == ["Viewer"]


def test_extract_roles_honours_role_map_override(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_ROLE_MAP", "kc-reader:Viewer,kc-admin:Administrator")
    claims = {"realm_access": {"roles": ["kc-reader", "kc-admin"]}}
    assert identity.extract_roles(claims) == ["Viewer", "Administrator"]


def test_resolve_user_dev_mode(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "dev")
    u = identity.resolve_user("analyst", "s1")
    assert u.roles == ["Analyst"] and u.user_id == "analyst"
    with pytest.raises(Exception):
        identity.resolve_user("nobody")


def _pkg(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None
