"""The Entra application configured under Annuaires also serves for sign-in when no SSO variables
are set. Variables that are set always win: on the CrashTest stack the mock SSO stays in front."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient
from test_auth_flow import login_as, make_app

from lcit_sign import models  # noqa: F401 - registers tables
from lcit_sign.database import Base
from lcit_sign.models.directory import DirectoryConnectorConfig
from lcit_sign.services.crypto import encrypt_secret
from lcit_sign.services.sso import resolve_sso

TENANT = "73405479-f042-45d7-8149-c90341261b65"


def store_entra(app) -> None:
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as db:
        db.add(DirectoryConnectorConfig(
            source="entra",
            settings_json=json.dumps({"tenant_id": TENANT, "client_id": "app-1"}),
            encrypted_secret=encrypt_secret(app.state.settings.master_key, "s3cret"),
        ))
        db.commit()


def test_environment_wins_on_a_normal_installation(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url, master_key="test-master-key-0123456789abcdef")
    with TestClient(app):
        store_entra(app)
        with app.state.session_factory() as db:
            sso = resolve_sso(db, app.state.settings)
        assert sso and sso.client_id == "test-client"


def test_the_directory_application_is_used_when_no_variables(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url, master_key="test-master-key-0123456789abcdef")
    with TestClient(app):
        store_entra(app)
        settings = app.state.settings.model_copy(update={"oidc_issuer": "", "oidc_client_id": ""})
        with app.state.session_factory() as db:
            sso = resolve_sso(db, settings)
        assert sso and sso.provider == "entra" and sso.client_id == "app-1"
        assert sso.issuer == f"https://login.microsoftonline.com/{TENANT}/v2.0"


def test_crashtest_keeps_the_mock_oidc_even_with_an_entra_directory(tmp_path, mock_oidc_base_url):
    app = make_app(
        tmp_path, mock_oidc_base_url, master_key="test-master-key-0123456789abcdef", crashtest=True
    )
    with TestClient(app) as client:
        settings = app.state.settings
        assert settings.crashtest and settings.oidc_issuer == mock_oidc_base_url
        store_entra(app)
        with app.state.session_factory() as db:
            sso = resolve_sso(db, settings)
        # The mock stays the issuer; Entra is reached through it, never directly.
        assert sso and sso.issuer == mock_oidc_base_url and sso.client_id == "test-client"
        assert "login.microsoftonline.com" not in sso.issuer
        options = client.get("/api/auth/options").json()
        assert options["sso"] is True and options["provider"] != "entra"
        assert options["test_sso"] is False  # the mock is the main button, not a second one
        login_as(client, mock_oidc_base_url, sub="u-rh-2")
        assert client.get("/api/auth/me").json()["email"] == "sophie.bernard@lcit-test.local"


def test_no_second_button_outside_crashtest(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url, master_key="test-master-key-0123456789abcdef")
    with TestClient(app) as client:
        store_entra(app)
        assert client.get("/api/auth/options").json()["test_sso"] is False
        assert client.get("/api/auth/login?test_sso=true").status_code == 503
