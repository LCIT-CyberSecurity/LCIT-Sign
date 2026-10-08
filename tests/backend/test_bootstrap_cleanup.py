"""A fresh installation is truly empty (the fictional directory belongs to CrashTest), production
refuses development secrets, and the last administrator keeps the role."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from test_auth_flow import login_as, make_app

from lcit_sign import models  # noqa: F401 - registers tables
from lcit_sign.app import create_app
from lcit_sign.config import Settings
from lcit_sign.database import Base
from lcit_sign.models.campaign import Campaign
from lcit_sign.models.directory import DirectoryConnectorConfig, Group
from lcit_sign.models.login_provider import LoginProvider
from lcit_sign.models.user import User

DEFAULT = "SecretPassword"  # noqa: S105 - the documented initial password
SECRETS = {"session_secret": "s" * 40, "master_key": "m" * 40}  # noqa: S106


def fresh(tmp_path, _oidc=None, **over):
    """A normal installation with nothing configured: no SSO, no directory."""
    app = create_app(Settings(
        database_url=f"sqlite:///{tmp_path}/test.db", session_secret="test-session-secret",
        cookie_secure=False, public_base_url="http://testserver",
        storage_root=str(tmp_path / "storage"), notification_worker_enabled=False, **over,
    ))
    client = TestClient(app)
    client.__enter__()
    Base.metadata.create_all(app.state.engine)
    r = client.post("/api/auth/local-login", json={"username": "admin", "password": DEFAULT})
    assert r.status_code == 204
    return app, client


def count(app, model) -> int:
    with app.state.session_factory() as db:
        return db.execute(select(func.count()).select_from(model)).scalar_one()


# --- a fresh normal installation ----------------------------------------------------------------


def test_a_fresh_installation_is_empty_but_for_the_system_account(tmp_path, mock_oidc_base_url):
    app, admin = fresh(tmp_path, mock_oidc_base_url)
    me = admin.get("/api/auth/me").json()
    assert sorted(me["roles"]) == ["ADMIN", "SIGNER"] and me["must_change_password"] is True
    assert [u["email"] for u in admin.get("/api/admin/users").json()] == [me["email"]]
    assert count(app, User) == 1 and count(app, Group) == 0 and count(app, Campaign) == 0
    assert count(app, LoginProvider) == 0 and count(app, DirectoryConnectorConfig) == 0
    assert admin.get("/api/admin/directory/groups").json() == []


def test_a_fresh_installation_offers_local_sign_in_only(tmp_path, mock_oidc_base_url):
    _, admin = fresh(tmp_path, mock_oidc_base_url)
    options = TestClient(admin.app).get("/api/auth/options").json()
    assert options["local"] is True and not options.get("sso") and not options.get("crashtest")
    status = admin.get("/api/admin/login-providers/status").json()
    assert status["managed_by_environment"] is False
    providers = admin.get("/api/admin/login-providers").json()
    assert not any(p["configured"] or p["active"] for p in providers)


def test_a_fresh_installation_has_no_directory_and_no_demonstration_one(
    tmp_path, mock_oidc_base_url
):
    app, admin = fresh(tmp_path, mock_oidc_base_url)
    sources = admin.get("/api/admin/directory/sources").json()
    assert [s["source"] for s in sources] == ["entra", "google", "ldap"]
    assert not any(s["active"] for s in sources)
    refused = admin.post("/api/admin/directory/sync")
    assert refused.status_code == 409 and "Aucun annuaire" in refused.json()["detail"]
    for call in (
        admin.post("/api/admin/directory/sync?source=local"),
        admin.post("/api/admin/directory/sources/local/activate"),
        admin.put("/api/admin/directory/sources/local/config", json={}),
    ):
        assert call.status_code == 404
    assert count(app, User) == 1 and count(app, Group) == 0


# --- CrashTest keeps its fictional directory ------------------------------------------------------


def test_crashtest_still_has_its_demonstration_directory(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url, crashtest=True)
    with TestClient(app) as admin:
        Base.metadata.create_all(app.state.engine)
        login_as(admin, mock_oidc_base_url, sub="u-direction-1")  # Alice, bootstrap admin
        sources = {s["source"]: s for s in admin.get("/api/admin/directory/sources").json()}
        assert sources["local"]["active"] is True
        run = admin.post("/api/admin/directory/sync").json()
        assert run["source"] == "local" and run["status"] == "SUCCESS" and run["groups_added"] == 6
        assert admin.get("/api/auth/options").json()["crashtest"] is True
        emails = {u["email"] for u in admin.get("/api/admin/users").json()}
        assert {"alice.martin@lcit-test.local", "bob.dupont@lcit-test.local"} <= emails


# --- production refuses development secrets -------------------------------------------------------


@pytest.mark.parametrize("environment", ["development", "test"])
def test_development_values_are_fine_outside_production(environment):
    Settings(environment=environment, session_secret="insecure-dev-secret-change-me",
             master_key="dev-only-insecure-master-key-change-me", cookie_secure=False)
    Settings(environment=environment)  # the bare defaults


def test_crashtest_keeps_its_development_values():
    Settings(crashtest=True, session_secret="crashtest-only-session-secret",
             master_key="crashtest-only-master-key-not-a-secret", cookie_secure=False)


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"session_secret": "insecure-dev-secret-change-me"}, "SESSION_SECRET"),
        ({"session_secret": "dev-only-insecure-secret-change-me"}, "SESSION_SECRET"),
        ({"session_secret": ""}, "SESSION_SECRET"),
        ({"master_key": "dev-only-insecure-master-key-change-me"}, "MASTER_KEY"),
        ({"master_key": ""}, "MASTER_KEY"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
    ],
)
def test_production_refuses_to_start_with_development_values(over, why):
    with pytest.raises(ValidationError, match=why):
        Settings(environment="production", **{"cookie_secure": True, **SECRETS, **over})


@pytest.mark.parametrize("field", ["session_secret", "master_key"])
def test_production_refuses_short_secrets_and_accepts_32_characters(field):
    secrets = dict(SECRETS)
    for short in ("x", "y" * 31):
        with pytest.raises(ValidationError, match="short"):
            Settings(environment="production", cookie_secure=True, **{**secrets, field: short})
    Settings(environment="production", cookie_secure=True, **{**secrets, field: "z" * 32})


@pytest.mark.parametrize("environment", ["development", "test"])
def test_short_secrets_are_fine_outside_production(environment):
    Settings(environment=environment, session_secret="x", master_key="y", cookie_secure=False)


def test_crashtest_may_use_short_secrets():
    Settings(crashtest=True, session_secret="x", master_key="y", cookie_secure=False)


def test_production_with_real_secrets_starts():
    Settings(environment="production", cookie_secure=True, **SECRETS)


def test_production_reads_its_secrets_from_files(tmp_path):
    (tmp_path / "s").write_text("x" * 40)
    (tmp_path / "m").write_text("y" * 40)
    settings = Settings(
        environment="production", session_secret_file=str(tmp_path / "s"),
        master_key_file=str(tmp_path / "m"),
    )
    assert settings.master_key == "y" * 40


# --- the last administrator ----------------------------------------------------------------------


def test_the_last_administrator_cannot_lose_the_role_but_one_of_two_can(
    tmp_path, mock_oidc_base_url
):
    app = make_app(tmp_path, mock_oidc_base_url)
    with TestClient(app) as alice, TestClient(app) as claire:
        Base.metadata.create_all(app.state.engine)
        login_as(alice, mock_oidc_base_url, sub="u-direction-1")  # bootstrap admin
        login_as(claire, mock_oidc_base_url, sub="u-compta-1")
        alice_id = alice.get("/api/auth/me").json()["id"]
        claire_id = claire.get("/api/auth/me").json()["id"]
        # Alice is the only administrator.
        only = alice.delete(f"/api/admin/users/{alice_id}/roles/ADMIN")
        assert only.status_code == 409 and "dernier administrateur" in only.json()["detail"]
        off = alice.patch(f"/api/admin/users/{alice_id}", json={"active": False})
        assert off.status_code == 409
        assert alice.delete(f"/api/admin/users/{alice_id}").status_code == 409
        assert "ADMIN" in alice.get("/api/auth/me").json()["roles"]
        # Other roles come off by the normal rules.
        assert alice.delete(f"/api/admin/users/{alice_id}/roles/SIGNER").status_code == 200
        # Two administrators: one may give the role up.
        grant = alice.post(f"/api/admin/users/{claire_id}/roles", json={"role": "ADMIN"})
        assert grant.status_code == 201
        assert alice.delete(f"/api/admin/users/{alice_id}/roles/ADMIN").status_code == 200
        # Claire is now the last one.
        assert claire.delete(f"/api/admin/users/{claire_id}/roles/ADMIN").status_code == 409
