from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_auth_flow import make_app

from lcit_sign import models  # noqa: F401 - registers tables
from lcit_sign.config import Settings
from lcit_sign.database import Base
from lcit_sign.models.audit import AuditEvent
from lcit_sign.models.user import User
from lcit_sign.services.passwords import (
    hash_password,
    is_acceptable_for_production,
    verify_password,
)

PASSWORD = "Une-phrase-secrete-longue-2026"  # noqa: S105
DEFAULT = "SecretPassword"  # noqa: S105 - the documented non-production default


def started(tmp_path, oidc, **overrides):
    app = make_app(tmp_path, oidc, **overrides)
    client = TestClient(app)
    client.__enter__()
    Base.metadata.create_all(app.state.engine)
    return app, client


def login(client, username="admin", password=PASSWORD):
    return client.post("/api/auth/local-login", json={"username": username, "password": password})


def test_a_fresh_non_production_deployment_has_the_default_admin_which_must_be_changed(
    tmp_path, mock_oidc_base_url
):
    app, client = started(tmp_path, mock_oidc_base_url)  # nothing configured
    assert client.get("/api/auth/options").json()["local"] is True
    assert login(client, password="not-it").status_code == 401
    assert login(client, password=DEFAULT).status_code == 204
    me = client.get("/api/auth/me").json()
    assert me["roles"] == ["ADMIN", "SIGNER"] and me["source"] == "builtin"
    assert me["must_change_password"] is True  # the interface nags until it is changed


def test_the_default_admin_works_in_production_too_and_is_flagged(tmp_path, mock_oidc_base_url):
    app, client = started(
        tmp_path, mock_oidc_base_url, environment="production", cookie_secure=True,
        master_key="a-real-master-key-for-this-test-0123456789",
    )
    client.base_url = "https://testserver"  # the cookie is Secure
    assert login(client, password=DEFAULT).status_code == 204
    assert client.get("/api/auth/me").json()["must_change_password"] is True
    # Diagnostics call it out as an error in production until it is changed.
    checks = {c["name"]: c for c in client.get("/api/admin/diagnostics").json()["checks"]}
    assert checks["builtin_admin"]["status"] == "ERROR"
    client.post(
        "/api/auth/change-password",
        json={"current_password": DEFAULT, "new_password": "Un-mot-de-passe-solide-2026"},
    )
    checks = {c["name"]: c for c in client.get("/api/admin/diagnostics").json()["checks"]}
    assert checks["builtin_admin"]["status"] == "OK"


def test_a_configured_initial_password_wins_over_the_default(tmp_path, mock_oidc_base_url):
    app, client = started(tmp_path, mock_oidc_base_url, local_admin_password=PASSWORD)
    assert login(client, password=DEFAULT).status_code == 401
    assert login(client, password=PASSWORD).status_code == 204
    assert client.get("/api/auth/me").json()["must_change_password"] is True


def test_the_admin_changes_the_password_and_the_reminder_stops(tmp_path, mock_oidc_base_url):
    app, client = started(tmp_path, mock_oidc_base_url)
    login(client, password=DEFAULT)
    other_session = TestClient(app)
    login(other_session, password=DEFAULT)

    change = client.post(
        "/api/auth/change-password",
        json={"current_password": DEFAULT, "new_password": "Un-mot-de-passe-solide-2026"},
    )
    assert change.status_code == 204, change.text
    assert client.get("/api/auth/me").json()["must_change_password"] is False
    assert other_session.get("/api/auth/me").status_code == 401  # other sessions ended

    # The old password is dead, the new one works, no reminder any more.
    fresh = TestClient(app)
    assert login(fresh, password=DEFAULT).status_code == 401
    assert login(fresh, password="Un-mot-de-passe-solide-2026").status_code == 204
    assert fresh.get("/api/auth/me").json()["must_change_password"] is False


def test_a_restart_never_overwrites_the_password_the_admin_chose(tmp_path, mock_oidc_base_url):
    from lcit_sign.services.local_auth import ensure_builtin_admin

    app, client = started(tmp_path, mock_oidc_base_url)
    login(client, password=DEFAULT)
    client.post(
        "/api/auth/change-password",
        json={"current_password": DEFAULT, "new_password": "Un-mot-de-passe-solide-2026"},
    )
    with app.state.session_factory() as db:  # what a restart does
        ensure_builtin_admin(db, app.state.settings)
    again = TestClient(app)
    assert login(again, password=DEFAULT).status_code == 401
    assert login(again, password="Un-mot-de-passe-solide-2026").status_code == 204


@pytest.mark.parametrize(
    ("new", "why"),
    [
        ("court", "12"),
        (DEFAULT, "différent"),
        ("abababababab", "variété"),
        ("password1234", "connu"),
    ],
)
def test_a_weak_or_unchanged_new_password_is_refused(tmp_path, mock_oidc_base_url, new, why):
    app, client = started(tmp_path, mock_oidc_base_url)
    login(client, password=DEFAULT)
    refused = client.post(
        "/api/auth/change-password", json={"current_password": DEFAULT, "new_password": new}
    )
    assert refused.status_code == 422
    assert client.get("/api/auth/me").json()["must_change_password"] is True
    wrong = client.post(
        "/api/auth/change-password",
        json={"current_password": "wrong", "new_password": "Un-mot-de-passe-solide-2026"},
    )
    assert wrong.status_code == 422


def test_an_sso_user_has_no_password_to_change(tmp_path, mock_oidc_base_url):
    from test_auth_flow import login_as

    app, client = started(tmp_path, mock_oidc_base_url)
    sso = TestClient(app)
    login_as(sso, mock_oidc_base_url, sub="u-it-1")
    assert sso.get("/api/auth/me").json()["must_change_password"] is False
    refused = sso.post(
        "/api/auth/change-password",
        json={"current_password": "x", "new_password": "Un-mot-de-passe-solide-2026"},
    )
    assert refused.status_code == 422 and "SSO" in refused.text


def test_wrong_credentials_are_refused_audited_and_throttled(tmp_path, mock_oidc_base_url):
    app, client = started(tmp_path, mock_oidc_base_url, local_admin_password=PASSWORD)
    assert login(client, password="nope").status_code == 401
    assert login(client, username="root").status_code == 401
    for _ in range(4):
        login(client, password="nope")
    # Five failures close the door — even for the right password.
    assert login(client).status_code == 429
    with app.state.session_factory() as db:
        failures = list(
            db.execute(select(AuditEvent).where(AuditEvent.action == "LOGIN_FAILURE")).scalars()
        )
    assert failures and all(PASSWORD not in str(e.metadata_json) for e in failures)


def test_an_sso_user_cannot_use_the_local_form(tmp_path, mock_oidc_base_url):
    from test_auth_flow import login_as

    app, client = started(tmp_path, mock_oidc_base_url, local_admin_password=PASSWORD)
    other = TestClient(app)
    login_as(other, mock_oidc_base_url, sub="u-it-1")  # a normal SSO user: no password at all
    other_email = other.get("/api/auth/me").json()["email"]
    assert login(client, username=other_email, password="whatever").status_code == 401
    with app.state.session_factory() as db:
        sso = db.execute(select(User).where(User.email == other_email)).scalar_one()
        assert sso.password_hash is None


def test_it_can_be_switched_off(tmp_path, mock_oidc_base_url):
    app, client = started(
        tmp_path, mock_oidc_base_url, local_admin_password=PASSWORD, local_auth_enabled=False
    )
    assert client.get("/api/auth/options").json()["local"] is False
    assert login(client).status_code == 404


def test_switching_it_off_disables_an_existing_account(tmp_path, mock_oidc_base_url):
    app, client = started(tmp_path, mock_oidc_base_url, local_admin_password=PASSWORD)
    assert login(client).status_code == 204
    client.post("/api/auth/logout")
    off = Settings(**{**app.state.settings.model_dump(), "local_auth_enabled": False})
    from lcit_sign.services.local_auth import ensure_builtin_admin

    with app.state.session_factory() as db:
        ensure_builtin_admin(db, off)
        user = db.execute(select(User).where(User.issuer == "builtin:local")).scalar_one()
        assert user.active is False and user.password_hash is None


def test_password_helpers():
    stored = hash_password("correct horse battery")
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("anything", None) and not verify_password("anything", "garbage")
    assert hash_password("x") != hash_password("x")  # salted
    assert is_acceptable_for_production(PASSWORD) is None
    assert is_acceptable_for_production("SecretPassword")


def test_the_password_is_read_from_a_secret_file_and_never_logged(
    tmp_path, mock_oidc_base_url, caplog
):
    secret = tmp_path / "pw"
    secret.write_text(PASSWORD + "\n")
    caplog.set_level(logging.DEBUG)
    app, client = started(tmp_path, mock_oidc_base_url, local_admin_password_file=str(secret))
    assert login(client).status_code == 204
    assert PASSWORD not in caplog.text
