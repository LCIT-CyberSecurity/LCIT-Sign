"""Administration > Connexion: the read-only "Tester la connexion" of the sign-in providers."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_auth_flow import login_as, make_app
from test_directory_connectors import TEST_MASTER_KEY, _admin

from lcit_sign.api.login_providers import get_login_http_client
from lcit_sign.models.audit import AuditEvent
from lcit_sign.models.user import User

TENANT = "73405479-f042-45d7-8149-c90341261b65"
CLIENT = "333a1a3e-1d45-4661-9c9e-2c91d7b0c5d3"
SECRET = "s3cr3t-value~Xyz"
GOOGLE_CLIENT = "123-abc.apps.googleusercontent.com"
GOOGLE_SECRET = "GOCSPX-g00gle-s3cret"


def make(tmp_path, oidc, handler):
    app = make_app(tmp_path, oidc, master_key=TEST_MASTER_KEY)

    def client():
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            yield c

    app.dependency_overrides[get_login_http_client] = client
    return app


def entra_handler(token_status=200, token_body=None, discovery_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openid-configuration" in url:
            return httpx.Response(discovery_status, json={"issuer": "x"})
        assert "oauth2/v2.0/token" in url
        return httpx.Response(token_status, json=token_body or {"access_token": "tok-abc"})

    return handler


def setup_entra(admin):
    r = admin.put(
        "/api/admin/login-providers/entra",
        json={"client_id": CLIENT, "tenant_id": TENANT, "client_secret": SECRET},
    )
    assert r.status_code == 200, r.text


def audit(app):
    with app.state.session_factory() as db:
        return [e for e in db.execute(select(AuditEvent)).scalars()
                if e.action == "LOGIN_PROVIDER_TESTED"]


def test_entra_everything_works_and_no_secret_leaks(tmp_path, mock_oidc_base_url):
    app = make(tmp_path, mock_oidc_base_url, entra_handler())
    admin = _admin(app, mock_oidc_base_url)
    setup_entra(admin)
    response = admin.post("/api/admin/login-providers/entra/test")
    body = response.json()
    assert body["status"] == "OK", body
    assert [c["name"] for c in body["checks"]] == ["discovery", "credentials"]
    assert SECRET not in response.text and "tok-abc" not in response.text


@pytest.mark.parametrize(
    ("code", "provider"),
    [(7000215, "AADSTS7000215"), (7000222, "AADSTS7000222"), (700016, "AADSTS700016")],
)
def test_entra_refused_credentials_name_the_provider_code(
    tmp_path, mock_oidc_base_url, code, provider
):
    handler = entra_handler(401, {"error": "invalid_client", "error_codes": [code],
                                  "error_description": "raw text with the secret " + SECRET})
    app = make(tmp_path, mock_oidc_base_url, handler)
    admin = _admin(app, mock_oidc_base_url)
    setup_entra(admin)
    response = admin.post("/api/admin/login-providers/entra/test")
    last = response.json()["checks"][-1]
    assert (last["name"], last["status"], last["provider_code"]) == (
        "credentials", "ERROR", provider)
    assert last["action"]
    assert SECRET not in response.text and "raw text" not in response.text


def test_entra_unknown_tenant_stops_at_discovery(tmp_path, mock_oidc_base_url):
    app = make(tmp_path, mock_oidc_base_url, entra_handler(discovery_status=400))
    admin = _admin(app, mock_oidc_base_url)
    setup_entra(admin)
    checks = admin.post("/api/admin/login-providers/entra/test").json()["checks"]
    assert [(c["name"], c["code"]) for c in checks] == [("discovery", "TENANT_NOT_FOUND")]


def test_entra_network_failure(tmp_path, mock_oidc_base_url):
    def handler(request):
        raise httpx.ConnectError("no route")

    app = make(tmp_path, mock_oidc_base_url, handler)
    admin = _admin(app, mock_oidc_base_url)
    setup_entra(admin)
    checks = admin.post("/api/admin/login-providers/entra/test").json()["checks"]
    assert checks[0]["name"] == "discovery" and checks[0]["status"] == "ERROR"


def google_handler(error=None, status=400):
    def handler(request: httpx.Request) -> httpx.Response:
        if "openid-configuration" in str(request.url):
            return httpx.Response(200, json={"issuer": "https://accounts.google.com"})
        assert b"lcit-sign-connection-test" in request.content
        return httpx.Response(status, json={"error": error or "invalid_grant"})

    return handler


def setup_google(admin):
    r = admin.put(
        "/api/admin/login-providers/google",
        json={"client_id": GOOGLE_CLIENT, "client_secret": GOOGLE_SECRET},
    )
    assert r.status_code == 200, r.text


def test_google_accepted_client_is_ok_though_the_fake_code_is_refused(
    tmp_path, mock_oidc_base_url
):
    app = make(tmp_path, mock_oidc_base_url, google_handler())
    admin = _admin(app, mock_oidc_base_url)
    setup_google(admin)
    response = admin.post("/api/admin/login-providers/google/test")
    assert response.json()["status"] == "OK", response.json()
    assert GOOGLE_SECRET not in response.text


def test_google_invalid_client_is_a_credentials_problem(tmp_path, mock_oidc_base_url):
    app = make(tmp_path, mock_oidc_base_url, google_handler("invalid_client", 401))
    admin = _admin(app, mock_oidc_base_url)
    setup_google(admin)
    response = admin.post("/api/admin/login-providers/google/test")
    last = response.json()["checks"][-1]
    assert (last["code"], last["provider_code"]) == ("INVALID_CREDENTIALS", "invalid_client")
    assert GOOGLE_SECRET not in response.text


def test_the_test_is_audited_without_any_secret_and_writes_nothing_else(
    tmp_path, mock_oidc_base_url
):
    handler = entra_handler(401, {"error_codes": [7000222]})
    app = make(tmp_path, mock_oidc_base_url, handler)
    admin = _admin(app, mock_oidc_base_url)
    setup_entra(admin)
    with app.state.session_factory() as db:
        users_before = db.scalar(select(func.count()).select_from(User))
    admin.post("/api/admin/login-providers/entra/test")
    (event,) = audit(app)
    assert event.metadata_json == {
        "provider": "entra", "status": "ERROR", "error_code": "SECRET_EXPIRED",
        "provider_code": "AADSTS7000222",
    }
    assert SECRET not in json.dumps(event.metadata_json)
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == users_before


def test_administrators_only_and_a_saved_provider_is_needed(tmp_path, mock_oidc_base_url):
    app = make(tmp_path, mock_oidc_base_url, entra_handler())
    admin = _admin(app, mock_oidc_base_url)
    assert admin.post("/api/admin/login-providers/entra/test").status_code == 409
    assert admin.post("/api/admin/login-providers/nope/test").status_code == 404
    setup_entra(admin)
    with TestClient(app) as anonymous:
        assert anonymous.post("/api/admin/login-providers/entra/test").status_code == 401
    with TestClient(app) as signer:
        login_as(signer, mock_oidc_base_url, sub="u-sales-1")
        assert signer.post("/api/admin/login-providers/entra/test").status_code == 403
