"""Keycloak client helpers: URL building, PKCE, and grant request shapes (httpx mocked)."""
import urllib.parse as up

import pytest

from authclient import keycloak_client as kc


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "http://kc:8080")
    monkeypatch.setenv("KEYCLOAK_REALM", "abc-bank")


def test_issuer_and_endpoints():
    assert kc.issuer() == "http://kc:8080/realms/abc-bank"


def test_pkce_verifier_and_challenge_differ():
    v, c = kc.new_pkce()
    assert v and c and v != c
    assert "=" not in v and "=" not in c  # url-safe, unpadded


def test_sso_login_url_defaults_to_keycloak_login_no_broker(monkeypatch):
    # default: no KEYCLOAK_SSO_IDP -> go to Keycloak's own login page, NO broker hint
    monkeypatch.delenv("KEYCLOAK_SSO_IDP", raising=False)
    url = kc.sso_login_url("http://localhost:8501/", code_challenge="CHAL", state="xyz")
    q = dict(up.parse_qsl(up.urlparse(url).query))
    assert q["response_type"] == "code"
    assert q["code_challenge"] == "CHAL" and q["code_challenge_method"] == "S256"
    assert "kc_idp_hint" not in q  # must NOT force an unconfigured broker
    assert q["client_id"] == "ai-assistant-web"
    assert q["redirect_uri"] == "http://localhost:8501/"


def test_sso_login_url_adds_broker_hint_only_when_configured(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_SSO_IDP", "corporate-sso")
    url = kc.sso_login_url("http://localhost:8501/", code_challenge="CHAL")
    q = dict(up.parse_qsl(up.urlparse(url).query))
    assert q["kc_idp_hint"] == "corporate-sso"


def test_password_login_posts_password_grant(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"access_token": "TOK"}

    def fake_post(url, data=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        return _Resp()

    monkeypatch.setattr(kc.httpx, "post", fake_post)
    tok = kc.password_login("analyst", "pw")
    assert tok["access_token"] == "TOK"
    assert captured["url"].endswith("/protocol/openid-connect/token")
    assert captured["data"]["grant_type"] == "password"
    assert captured["data"]["username"] == "analyst"
    assert captured["data"]["client_id"] == "ai-assistant-admin"


def test_exchange_code_posts_authorization_code(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"access_token": "TOK2"}

    monkeypatch.setattr(kc.httpx, "post",
                        lambda url, data=None, timeout=None: captured.update(data=data) or _Resp())
    kc.exchange_code("CODE", "http://localhost:8501/", "VERIFIER")
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["code"] == "CODE"
    assert captured["data"]["code_verifier"] == "VERIFIER"
