"""Local accounts: people an administrator gave a password to, next to the SSO. And which
provider's button the sign-in page shows."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_auth_flow import login_as
from test_campaigns import setup_campaign_fixture

from lcit_sign.app import create_app
from lcit_sign.config import Settings
from lcit_sign.models.audit import AuditEvent
from lcit_sign.models.user import User


def app_with(tmp_path, issuer: str, client_id: str, secret: str, provider: str = ""):
    return create_app(Settings(
        database_url=f"sqlite:///{tmp_path}/options.db", session_secret="s", cookie_secure=False,
        public_base_url="http://testserver", storage_root=str(tmp_path / "storage"),
        oidc_issuer=issuer, oidc_client_id=client_id, oidc_client_secret=secret,
        oidc_provider=provider, notification_worker_enabled=False,
    ))


PASSWORD = "bob-initial-2026"  # noqa: S105
EMAIL = "bob.local@corp.test"


def create_local(admin, email=EMAIL, password=PASSWORD, roles=("SIGNER",)):
    return admin.post("/api/admin/users", json={
        "email": email, "given_name": "Bob", "family_name": "Local", "roles": list(roles),
        "auth_method": "local", "password": password,
    })


def local_login(app, email=EMAIL, password=PASSWORD):
    client = TestClient(app)
    client.__enter__()
    return client, client.post(
        "/api/auth/local-login", json={"username": email, "password": password}
    )


def test_an_administrator_creates_a_local_account_and_the_password_goes_nowhere(
    tmp_path, mock_oidc_base_url
):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    created = create_local(admin)
    assert created.status_code == 201, created.text
    shown = created.json()
    assert shown["source"] == "password" and shown["email"] == EMAIL
    for text in (created.text, admin.get("/api/admin/users").text):
        assert PASSWORD not in text and "password_hash" not in text and "scrypt" not in text

    with app.state.session_factory() as db:
        row = db.execute(select(User).where(User.email == EMAIL)).scalar_one()
        assert row.password_hash and row.password_hash.startswith("scrypt$")
        assert PASSWORD not in row.password_hash
        assert row.must_change_password is True
        events = list(db.execute(select(AuditEvent)).scalars())
        assert all(PASSWORD not in str(e.metadata_json) for e in events)


def test_a_local_account_needs_a_real_password_and_an_sso_one_has_none(
    tmp_path, mock_oidc_base_url
):
    _, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    assert admin.post("/api/admin/users", json={
        "email": "a@corp.test", "auth_method": "local"}).status_code == 422
    short = create_local(admin, email="b@corp.test", password="court")
    assert short.status_code == 422 and "8 caractères" in short.json()["detail"]
    with_password = admin.post("/api/admin/users", json={
        "email": "c@corp.test", "auth_method": "sso", "password": "whatever-it-is"})
    assert with_password.status_code == 422
    plain = admin.post("/api/admin/users", json={"email": "d@corp.test"})
    assert plain.status_code == 201 and plain.json()["source"] == "manual"


def test_a_local_account_signs_in_with_its_password_and_must_change_it(
    tmp_path, mock_oidc_base_url
):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    create_local(admin)
    client, ok = local_login(app)
    assert ok.status_code == 204
    me = client.get("/api/auth/me").json()
    assert me["email"] == EMAIL and me["source"] == "local" and me["must_change_password"] is True

    changed = client.post("/api/auth/change-password", json={
        "current_password": PASSWORD, "new_password": "Une-phrase-secrete-longue-2026"})
    assert changed.status_code == 204
    assert client.get("/api/auth/me").json()["must_change_password"] is False
    assert local_login(app)[1].status_code == 401  # the first password no longer works
    assert local_login(app, password="Une-phrase-secrete-longue-2026")[1].status_code == 204


def test_wrong_password_and_disabled_account_are_refused(tmp_path, mock_oidc_base_url):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    user_id = create_local(admin).json()["id"]
    assert local_login(app, password="not-it")[1].status_code == 401
    assert admin.patch(f"/api/admin/users/{user_id}", json={"active": False}).status_code == 200
    assert local_login(app)[1].status_code == 401
    with app.state.session_factory() as db:
        failures = [e for e in db.execute(select(AuditEvent)).scalars()
                    if e.action == "LOGIN_FAILURE"]
        assert failures and all(PASSWORD not in str(e.metadata_json) for e in failures)


def test_an_sso_account_cannot_sign_in_locally(tmp_path, mock_oidc_base_url):
    app, admin, _operator, signer, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    # No password here: they sign in by SSO and have nothing to change.
    assert signer.get("/api/auth/me").json()["source"] == "sso"
    sso_email = signer.get("/api/auth/me").json()["email"]
    assert local_login(app, email=sso_email, password="anything-at-all")[1].status_code == 401
    manual = admin.post("/api/admin/users", json={"email": "manual@corp.test"}).json()
    assert local_login(app, email=manual["email"], password="anything-at-all")[1].status_code == 401


def test_a_local_account_is_the_same_person_when_they_use_the_sso(tmp_path, mock_oidc_base_url):
    """The SSO finds the account an administrator made for this address: same user, same roles,
    and the password keeps working."""
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    email = "charlie.durand@lcit-test.local"  # an identity of the mock SSO
    created = create_local(admin, email=email, roles=("SIGNER",))
    assert created.status_code == 201
    before = created.json()["id"]
    sso = TestClient(app)
    login_as(sso, mock_oidc_base_url, sub="u-compta-1")
    me = sso.get("/api/auth/me").json()
    assert me["id"] == before and "SIGNER" in me["roles"]
    assert local_login(app, email=email)[1].status_code == 204
    with app.state.session_factory() as db:
        assert len(list(db.execute(select(User).where(User.email == email)).scalars())) == 1


@pytest.mark.parametrize(
    ("issuer", "explicit", "expected"),
    [
        ("https://login.microsoftonline.com/t-1/v2.0", "", "entra"),
        ("https://sts.windows.net/t-1/", "", "entra"),
        ("https://accounts.google.com", "", "google"),
        ("https://sso.corp.test/realms/lcit", "", "generic"),
        ("https://sso.corp.test/realms/lcit", "entra", "entra"),
        ("", "", None),
    ],
)
def test_the_sign_in_page_knows_which_provider_is_configured(
    tmp_path, issuer, explicit, expected
):
    app = app_with(tmp_path, issuer, "id" if issuer else "", "s" if issuer else "", explicit)
    options = TestClient(app).get("/api/auth/options").json()
    assert options == {
        "sso": expected is not None, "provider": expected, "local": True, "crashtest": False}


def test_without_a_complete_sso_only_the_local_form_is_offered(tmp_path):
    app = app_with(tmp_path, "https://sso.corp.test/realms/lcit", "", "")
    assert TestClient(app).get("/api/auth/options").json()["sso"] is False
