from __future__ import annotations

import json

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from test_auth_flow import login_as, make_app
from test_campaigns import setup_campaign_fixture

from lcit_sign import models  # noqa: F401
from lcit_sign.api.directory import get_directory_http_client
from lcit_sign.database import Base
from lcit_sign.models.directory import DirectorySyncRun, Group
from lcit_sign.models.user import User

TEST_MASTER_KEY = "test-master-key-not-for-production-use"  # noqa: S105


def _entra_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "oauth2/v2.0/token" in url:
        return httpx.Response(200, json={"access_token": "tok"})
    assert request.headers["Authorization"] == "Bearer tok"
    if "/users?" in url and "page2" not in url:
        return httpx.Response(200, json={
            "value": [
                {"id": "e1", "mail": "Ann.One@corp.test", "givenName": "Ann",
                 "surname": "One", "accountEnabled": True},
                {"id": "e2", "userPrincipalName": "bo.two@corp.test",
                 "displayName": "Bo Two", "accountEnabled": False},
            ],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/users?page2",
        })
    if "page2" in url:
        return httpx.Response(200, json={"value": [
            {"id": "e3", "mail": "cy.three@corp.test", "givenName": "Cy",
             "surname": "Three", "accountEnabled": True},
            {"id": "e4", "accountEnabled": True},  # no mail at all: skipped
        ]})
    if "/groups?" in url:
        return httpx.Response(200, json={"value": [
            {"id": "g1", "displayName": "Finance", "description": "Money"},
        ]})
    if "/groups/g1/members" in url:
        return httpx.Response(200, json={"value": [
            {"@odata.type": "#microsoft.graph.user", "id": "e1"},
            {"@odata.type": "#microsoft.graph.user", "id": "e3"},
            {"@odata.type": "#microsoft.graph.group", "id": "nested"},
        ]})
    return httpx.Response(404)


def _entra_app(tmp_path, oidc, handler=_entra_handler):
    app = make_app(
        tmp_path, oidc, master_key=TEST_MASTER_KEY,
        entra_tenant_id="t", entra_client_id="c", entra_client_secret="s",
    )

    def client():
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            yield c

    app.dependency_overrides[get_directory_http_client] = client
    return app


def _admin(app, oidc):
    from fastapi.testclient import TestClient

    admin = TestClient(app)
    admin.__enter__()
    Base.metadata.create_all(app.state.engine)
    login_as(admin, oidc, sub="u-direction-1")
    return admin


def test_sources_listing(tmp_path, mock_oidc_base_url):
    app = _entra_app(tmp_path, mock_oidc_base_url)
    admin = _admin(app, mock_oidc_base_url)
    sources = {s["source"]: s["configured"] for s in
               admin.get("/api/admin/directory/sources").json()}
    assert sources == {"local": True, "entra": True, "google": False}


def test_entra_sync(tmp_path, mock_oidc_base_url):
    app = _entra_app(tmp_path, mock_oidc_base_url)
    admin = _admin(app, mock_oidc_base_url)
    run = admin.post("/api/admin/directory/sync?source=entra").json()
    assert run["status"] == "SUCCESS", run
    assert (run["users_added"], run["groups_added"], run["memberships_added"]) == (3, 1, 2)
    groups = admin.get("/api/admin/directory/groups").json()
    assert [(g["name"], g["member_count"]) for g in groups] == [("Finance", 2)]
    again = admin.post("/api/admin/directory/sync?source=entra").json()
    assert (again["users_added"], again["users_updated"], again["memberships_added"]) == (
        0, 3, 0)

    with app.state.session_factory() as db:
        bo = db.execute(select(User).where(User.email == "bo.two@corp.test")).scalar_one()
        assert bo.active is False
        assert (bo.given_name, bo.family_name) == ("Bo", "Two")
        assert db.execute(select(User).where(User.email == "ann.one@corp.test")).scalar_one()


def test_entra_failure_touches_nothing(tmp_path, mock_oidc_base_url):
    state = {"fail": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"]:
            return httpx.Response(500)
        return _entra_handler(request)

    app = _entra_app(tmp_path, mock_oidc_base_url, handler)
    admin = _admin(app, mock_oidc_base_url)
    admin.post("/api/admin/directory/sync?source=entra")
    state["fail"] = True
    run = admin.post("/api/admin/directory/sync?source=entra").json()
    assert run["status"] == "FAILED"
    assert "token request failed" in run["error"]
    with app.state.session_factory() as db:
        assert db.execute(select(User).where(User.email == "ann.one@corp.test")
                          ).scalar_one().active is True
        assert db.execute(select(Group).where(Group.source == "entra")).scalar_one().active


def test_removed_upstream_user_is_deactivated_and_group_deactivated(tmp_path, mock_oidc_base_url):
    state = {"empty": False}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if state["empty"] and ("/users?" in url or "/groups?" in url or "page2" in url):
            return httpx.Response(200, json={"value": []})
        return _entra_handler(request)

    app = _entra_app(tmp_path, mock_oidc_base_url, handler)
    admin = _admin(app, mock_oidc_base_url)
    admin.post("/api/admin/directory/sync?source=entra")
    state["empty"] = True
    run = admin.post("/api/admin/directory/sync?source=entra").json()
    assert run["users_deactivated"] == 2  # Bo was already inactive
    with app.state.session_factory() as db:
        assert not db.execute(select(Group).where(Group.source == "entra")).scalar_one().active


def test_unconfigured_and_unknown_sources(tmp_path, mock_oidc_base_url):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    assert admin.post("/api/admin/directory/sync?source=entra").status_code == 409
    assert admin.post("/api/admin/directory/sync?source=nope").status_code == 404
    assert admin.post("/api/admin/directory/sync").json()["source"] == "local"


def test_google_sync(tmp_path, mock_oidc_base_url):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    sa_json = json.dumps({"client_email": "sa@proj.iam.test", "private_key": pem})
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "oauth2.googleapis.com":
            body = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            seen["assertion"] = body["assertion"]
            return httpx.Response(200, json={"access_token": "gtok"})
        assert request.headers["Authorization"] == "Bearer gtok"
        if url.path.endswith("/users"):
            if url.params.get("pageToken") == "p2":
                return httpx.Response(200, json={"users": [
                    {"id": "u2", "primaryEmail": "Zed@corp.test", "suspended": True,
                     "name": {"givenName": "Zed", "familyName": "Z"}}]})
            return httpx.Response(200, json={"users": [
                {"id": "u1", "primaryEmail": "yan@corp.test",
                 "name": {"givenName": "Yan", "familyName": "Y"}}], "nextPageToken": "p2"})
        if url.path.endswith("/groups"):
            return httpx.Response(200, json={"groups": [
                {"id": "gg1", "email": "team@corp.test", "name": "Team"}]})
        if url.path.endswith("/groups/gg1/members"):
            return httpx.Response(200, json={"members": [
                {"id": "u1", "type": "USER"}, {"id": "u2", "type": "USER"},
                {"id": "x", "type": "GROUP"}]})
        return httpx.Response(404)

    app = make_app(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY,
        google_service_account_json=sa_json, google_admin_email="admin@corp.test",
    )

    def client():
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            yield c

    app.dependency_overrides[get_directory_http_client] = client
    admin = _admin(app, mock_oidc_base_url)
    run = admin.post("/api/admin/directory/sync?source=google").json()
    assert run["status"] == "SUCCESS", run
    assert (run["users_added"], run["groups_added"], run["memberships_added"]) == (2, 1, 2)
    # The assertion is a well-formed 3-part JWT.
    assert len(seen["assertion"].split(".")) == 3
    with app.state.session_factory() as db:
        zed = db.execute(select(User).where(User.email == "zed@corp.test")).scalar_one()
        assert zed.active is False
        assert db.execute(select(DirectorySyncRun)).scalars().first().source == "google"


def test_google_invalid_credentials_is_conflict(tmp_path, mock_oidc_base_url):
    app = make_app(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY,
        google_service_account_json="not json", google_admin_email="a@corp.test",
    )
    admin = _admin(app, mock_oidc_base_url)
    assert admin.post("/api/admin/directory/sync?source=google").status_code == 409
