"""Sign-in providers set up by an administrator (Administration > Connexion): stored encrypted, one
button each, chosen by the login URL and remembered through the callback."""
from __future__ import annotations

from fastapi.testclient import TestClient
from test_auth_flow import login_as, make_app

from lcit_sign import models  # noqa: F401 - registers tables
from lcit_sign.database import Base
from lcit_sign.models.login_provider import LoginProvider
from lcit_sign.services.sso import available_sso, resolve_sso

TENANT = "73405479-f042-45d7-8149-c90341261b65"
CLIENT = "333a1a3e-1d45-4661-9c9e-2c91d7b0c5d3"
MASTER = "test-master-key-0123456789abcdef"


def admin_client(tmp_path, oidc):
    app = make_app(tmp_path, oidc, master_key=MASTER)
    client = TestClient(app)
    client.__enter__()
    Base.metadata.create_all(app.state.engine)
    login_as(client, oidc, sub="u-direction-1")
    return app, client


def without_environment_sso(app) -> None:
    """The LCIT_SIGN_OIDC_* variables decide the SSO when they are set; these tests are about
    the providers an administrator sets up, so the environment's is taken out after sign-in."""
    app.state.settings = app.state.settings.model_copy(update={"oidc_issuer": ""})


def test_nothing_is_offered_until_an_administrator_sets_it_up(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url, master_key=MASTER)
    app.state.settings = app.state.settings.model_copy(update={"oidc_issuer": ""})
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)
        options = client.get("/api/auth/options").json()
        assert options["sso"] is False and "providers" not in options
        assert client.get("/api/auth/login").status_code == 503


def test_microsoft_and_google_are_stored_encrypted_and_only_one_is_active(
    tmp_path, mock_oidc_base_url
):
    app, admin = admin_client(tmp_path, mock_oidc_base_url)
    without_environment_sso(app)
    put = admin.put("/api/admin/login-providers/entra", json={
        "client_id": CLIENT, "tenant_id": TENANT, "client_secret": "s3cret-value-xyz"})
    assert put.status_code == 200 and "s3cret" not in put.text
    assert put.json()["redirect_uri"] == "http://testserver/api/auth/callback"
    assert put.json()["active"] is True
    # Saving a second provider makes it the one in use; the first stays configured, inactive.
    assert admin.put("/api/admin/login-providers/google", json={
        "client_id": "123-abc.apps.googleusercontent.com", "client_secret": "g-secret-value"
    }).status_code == 200
    listed = admin.get("/api/admin/login-providers")
    assert "s3cret" not in listed.text and "g-secret" not in listed.text
    assert [(p["provider"], p["configured"], p["active"]) for p in listed.json()] == [
        ("entra", True, False), ("google", True, True)]
    with app.state.session_factory() as db:
        row = db.get(LoginProvider, "entra")
        assert row and "s3cret" not in row.encrypted_secret
        assert [(c.key, c.provider) for c in available_sso(db, app.state.settings)] == [
            ("google", "google")]
    client = TestClient(app)
    options = client.get("/api/auth/options").json()
    assert options["sso"] is True and options["provider"] == "google"
    # Switching: Microsoft becomes the only one offered, nothing is retyped.
    assert admin.post("/api/admin/login-providers/entra/activate").status_code == 200
    assert client.get("/api/auth/options").json()["provider"] == "entra"
    assert [p["active"] for p in admin.get("/api/admin/login-providers").json()] == [True, False]
    assert admin.post("/api/admin/login-providers/nope/activate").status_code == 404


def test_the_environment_variables_win_and_the_page_says_so(tmp_path, mock_oidc_base_url):
    app, admin = admin_client(tmp_path, mock_oidc_base_url)  # the environment's SSO is set
    admin.put("/api/admin/login-providers/entra", json={
        "client_id": CLIENT, "tenant_id": TENANT, "client_secret": "s3cret-value-xyz"})
    assert admin.get("/api/admin/login-providers/status").json()["managed_by_environment"] is True
    with app.state.session_factory() as db:
        assert [c.key for c in available_sso(db, app.state.settings)] == ["sso"]
    without_environment_sso(app)
    assert admin.get("/api/admin/login-providers/status").json()["managed_by_environment"] is False
    assert TestClient(app).get("/api/auth/options").json()["provider"] == "entra"


def test_the_callback_remembers_which_sso_started_the_sign_in(tmp_path, mock_oidc_base_url):
    app, admin = admin_client(tmp_path, mock_oidc_base_url)
    admin.put("/api/admin/login-providers/google", json={
        "client_id": "123-abc.apps.googleusercontent.com", "client_secret": "g-secret-value"})
    with app.state.session_factory() as db:
        # One SSO is in use; asking for another by name finds nothing.
        assert resolve_sso(db, app.state.settings).issuer == mock_oidc_base_url
        assert resolve_sso(db, app.state.settings, "google") is None
        assert resolve_sso(db, app.state.settings, "sso").issuer == mock_oidc_base_url
    other = TestClient(app)
    assert other.get("/api/auth/login?provider=entra").status_code == 503
    login_as(other, mock_oidc_base_url, sub="u-rh-2", path="/api/auth/login?provider=sso")
    assert other.get("/api/auth/me").status_code == 200


def test_a_secret_that_is_really_an_id_is_refused_and_only_an_admin_can_configure(
    tmp_path, mock_oidc_base_url
):
    app, admin = admin_client(tmp_path, mock_oidc_base_url)
    mixed = admin.put("/api/admin/login-providers/entra", json={
        "client_id": CLIENT, "tenant_id": TENANT, "client_secret": CLIENT})
    assert mixed.status_code == 422 and "VALEUR" in mixed.json()["detail"]
    assert admin.put("/api/admin/login-providers/entra", json={
        "client_id": CLIENT, "tenant_id": TENANT}).status_code == 422  # no secret yet
    assert admin.put("/api/admin/login-providers/nope", json={"client_id": "x"}).status_code == 404
    nobody = TestClient(app)
    login_as(nobody, mock_oidc_base_url, sub="u-rh-1")
    assert nobody.get("/api/admin/login-providers").status_code == 403


def test_the_secret_can_stay_when_only_the_id_changes_and_a_provider_can_be_removed(
    tmp_path, mock_oidc_base_url
):
    app, admin = admin_client(tmp_path, mock_oidc_base_url)
    body = {"client_id": CLIENT, "tenant_id": TENANT, "client_secret": "s3cret-value-xyz"}
    admin.put("/api/admin/login-providers/entra", json=body)
    with app.state.session_factory() as db:
        before = db.get(LoginProvider, "entra").encrypted_secret
    again = admin.put("/api/admin/login-providers/entra", json={
        "client_id": "444a1a3e-1d45-4661-9c9e-2c91d7b0c5d3", "tenant_id": TENANT})
    assert again.status_code == 200
    with app.state.session_factory() as db:
        assert db.get(LoginProvider, "entra").encrypted_secret == before
    assert admin.delete("/api/admin/login-providers/entra").status_code == 204
    assert admin.delete("/api/admin/login-providers/entra").status_code == 404


def test_connections_export_and_import_keep_secrets_encrypted_and_check_the_key(
    tmp_path, mock_oidc_base_url, monkeypatch, capsys
):
    import io
    import json

    from lcit_sign import cli

    app, admin = admin_client(tmp_path, mock_oidc_base_url)
    admin.put("/api/admin/login-providers/entra", json={
        "client_id": CLIENT, "tenant_id": TENANT, "client_secret": "s3cret-value-xyz"})
    monkeypatch.setenv("LCIT_SIGN_DATABASE_URL", app.state.settings.database_url)
    monkeypatch.setenv("LCIT_SIGN_MASTER_KEY", MASTER)
    from lcit_sign.config import get_settings
    get_settings.cache_clear()
    assert cli.main(["export-connections"]) == 0
    out = capsys.readouterr().out
    # (the application may log JSON lines on stdout too: take the export itself)
    exported, _ = json.JSONDecoder().raw_decode(out[out.index('{\n  "version"'):])
    dumped = json.dumps(exported)
    assert "s3cret" not in dumped and exported["login_providers"][0]["client_id"] == CLIENT
    admin.delete("/api/admin/login-providers/entra")
    monkeypatch.setattr("sys.stdin", io.StringIO(dumped))
    assert cli.main(["import-connections"]) == 0
    assert admin.get("/api/admin/login-providers").json()[0]["configured"] is True
    assert admin.get("/api/admin/login-providers").json()[0]["active"] is True
    # Another master key cannot read the secrets: refused, nothing written.
    monkeypatch.setenv("LCIT_SIGN_MASTER_KEY", "another-master-key-0123456789abcdef")
    get_settings.cache_clear()
    monkeypatch.setattr("sys.stdin", io.StringIO(dumped))
    assert cli.main(["import-connections"]) == 1
    get_settings.cache_clear()


def test_the_mock_sso_gets_its_real_accounts_from_the_stored_connections(
    tmp_path, mock_oidc_base_url, monkeypatch, capsys
):
    """crashtest/start.sh builds the mock's private providers file from what was imported: a sign-in
    provider first, else the application of the Entra directory connector."""
    import json

    from lcit_sign import cli
    from lcit_sign.config import get_settings

    app, admin = admin_client(tmp_path, mock_oidc_base_url)
    monkeypatch.setenv("LCIT_SIGN_DATABASE_URL", app.state.settings.database_url)
    monkeypatch.setenv("LCIT_SIGN_MASTER_KEY", MASTER)
    get_settings.cache_clear()

    def exported() -> dict:
        assert cli.main(["export-mock-providers"]) == 0
        out = capsys.readouterr().out
        return json.loads(out.strip().splitlines()[-1])

    assert exported() == {}  # nothing stored: the mock keeps its fictional people only
    assert admin.put("/api/admin/directory/sources/entra/config", json={
        "fields": {"tenant_id": TENANT, "client_id": CLIENT}, "secret": "dir-secret-value~1"}
    ).status_code == 200
    assert exported() == {"entra": {
        "tenant_id": TENANT, "client_id": CLIENT, "client_secret": "dir-secret-value~1"}}
    admin.put("/api/admin/login-providers/entra", json={
        "client_id": "444a1a3e-1d45-4661-9c9e-2c91d7b0c5d3", "tenant_id": TENANT,
        "client_secret": "login-secret-value"})
    assert exported()["entra"]["client_secret"] == "login-secret-value"  # the sign-in app wins
    get_settings.cache_clear()
