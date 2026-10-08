from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from lcit_sign import models  # noqa: F401 - registers tables on Base.metadata
from lcit_sign.app import create_app
from lcit_sign.config import Settings
from lcit_sign.database import Base

BOOTSTRAP_ADMIN_EMAIL = "alice.martin@lcit-test.local"
NON_ADMIN_EMAIL = "bob.dupont@lcit-test.local"


def make_app(
    tmp_path, mock_oidc_base_url: str, *, bootstrap_admin: str = BOOTSTRAP_ADMIN_EMAIL, **overrides
):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        session_secret="test-session-secret",
        cookie_secure=overrides.pop("cookie_secure", False),
        public_base_url="http://testserver",
        oidc_issuer=mock_oidc_base_url,
        oidc_client_id="test-client",
        oidc_client_secret="test-secret",
        bootstrap_admin=bootstrap_admin,
        storage_root=str(tmp_path / "storage"),
        # Off by default in tests: the worker would otherwise race
        # Base.metadata.create_all() for a table that doesn't exist yet.
        notification_worker_enabled=overrides.pop("notification_worker_enabled", False),
        **overrides,
    )
    app = create_app(settings)
    return app


def login_as(
    client: TestClient, mock_oidc_base_url: str, *, sub: str, path: str = "/api/auth/login"
) -> httpx.Response:
    """Drive the full Authorization Code + PKCE dance against the real
    (locally running) mock OIDC provider, then hit our callback.
    """
    login_response = client.get(path, follow_redirects=False)
    assert login_response.status_code == 302
    authorize_url = login_response.headers["location"]
    assert authorize_url.startswith(mock_oidc_base_url + "/authorize")
    login_flow_cookie = login_response.cookies.get("lcit_sign_login")
    assert login_flow_cookie

    query = parse_qs(urlparse(authorize_url).query)
    choose_params = {key: value[0] for key, value in query.items()}
    choose_params["sub"] = sub

    with httpx.Client() as real_client:
        choose_response = real_client.get(
            f"{mock_oidc_base_url}/authorize/choose", params=choose_params, follow_redirects=False
        )
    assert choose_response.status_code == 307 or choose_response.status_code == 302
    callback_location = choose_response.headers["location"]
    callback_query = parse_qs(urlparse(callback_location).query)

    client.cookies.set("lcit_sign_login", login_flow_cookie)
    return client.get(
        "/api/auth/callback",
        params={"code": callback_query["code"][0], "state": callback_query["state"][0]},
        follow_redirects=False,
    )


def test_full_login_flow_grants_bootstrap_admin(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)

        callback_response = login_as(client, mock_oidc_base_url, sub="u-direction-1")
        assert callback_response.status_code == 302
        assert "lcit_sign_session" in callback_response.cookies

        me_response = client.get("/api/auth/me")
        assert me_response.status_code == 200
        body = me_response.json()
        assert body["email"] == BOOTSTRAP_ADMIN_EMAIL
        assert body["roles"] == ["ADMIN", "SIGNER"]


def test_non_bootstrap_user_signs_by_default_and_not_admin(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)

        login_as(client, mock_oidc_base_url, sub="u-rh-1")
        me_response = client.get("/api/auth/me")
        assert me_response.json()["roles"] == ["SIGNER"]  # everyone can sign by default

        admin_response = client.get("/api/admin/audit")
        assert admin_response.status_code == 403


def test_audit_trail_is_recorded_and_chain_is_valid(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)

        login_as(client, mock_oidc_base_url, sub="u-direction-1")

        audit_response = client.get("/api/admin/audit")
        assert audit_response.status_code == 200
        actions = [row["action"] for row in audit_response.json()]
        assert "LOGIN_SUCCESS" in actions

        integrity_response = client.get("/api/admin/audit/integrity")
        assert integrity_response.json() == {"valid": True, "first_invalid_sequence": None}


def test_logout_revokes_session(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)

        login_as(client, mock_oidc_base_url, sub="u-direction-1")
        assert client.get("/api/auth/me").status_code == 200

        logout_response = client.post("/api/auth/logout")
        assert logout_response.status_code == 204

        assert client.get("/api/auth/me").status_code == 401


def test_callback_rejects_state_mismatch(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)

        login_response = client.get("/api/auth/login", follow_redirects=False)
        assert login_response.status_code == 302

        tampered = client.get(
            "/api/auth/callback",
            params={"code": "irrelevant", "state": "not-the-real-state"},
            follow_redirects=False,
        )
        assert tampered.status_code == 400


def test_unauthenticated_request_is_rejected(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/api/admin/audit").status_code == 401
