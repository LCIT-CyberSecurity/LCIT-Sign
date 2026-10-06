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
from lcit_sign.models.directory import DirectoryConnectorConfig, DirectorySyncRun, Group
from lcit_sign.models.user import User
from lcit_sign.services.crypto import decrypt_secret

TEST_MASTER_KEY = "test-master-key-not-for-production-use"  # noqa: S105
ENTRA_FIELDS = {
    "tenant_id": "73405479-f042-45d7-8149-c90341261b65",
    "client_id": "9a8b7c6d-5e4f-4321-b0a9-8c7d6e5f4a3b",
}


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
    app = make_app(tmp_path, oidc, master_key=TEST_MASTER_KEY)

    def client():
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            yield c

    app.dependency_overrides[get_directory_http_client] = client
    return app


def _configure_entra(admin):
    response = admin.put(
        "/api/admin/directory/sources/entra/config",
        json={"fields": ENTRA_FIELDS, "secret": "s3cr3t-value~Xyz"},
    )
    assert response.status_code == 200, response.text
    return response


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
    _configure_entra(admin)
    sources = {s["source"]: s["configured"] for s in
               admin.get("/api/admin/directory/sources").json()}
    assert sources == {"local": True, "entra": True, "google": False, "ldap": False}


def test_entra_sync(tmp_path, mock_oidc_base_url):
    app = _entra_app(tmp_path, mock_oidc_base_url)
    admin = _admin(app, mock_oidc_base_url)
    _configure_entra(admin)
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
    _configure_entra(admin)
    admin.post("/api/admin/directory/sync?source=entra")
    state["fail"] = True
    run = admin.post("/api/admin/directory/sync?source=entra").json()
    assert run["status"] == "FAILED"
    assert "Microsoft a refusé" in run["error"]
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
    _configure_entra(admin)
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

    app = make_app(tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY)

    def client():
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            yield c

    app.dependency_overrides[get_directory_http_client] = client
    admin = _admin(app, mock_oidc_base_url)
    admin.put(
        "/api/admin/directory/sources/google/config",
        json={"fields": {"admin_email": "admin@corp.test"}, "secret": sa_json},
    )
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
    app = make_app(tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY)
    admin = _admin(app, mock_oidc_base_url)
    admin.put(
        "/api/admin/directory/sources/google/config",
        json={"fields": {"admin_email": "a@corp.test"}, "secret": "not json"},
    )
    assert admin.post("/api/admin/directory/sync?source=google").status_code == 409


def test_secret_is_encrypted_at_rest_and_never_returned(tmp_path, mock_oidc_base_url):
    app = _entra_app(tmp_path, mock_oidc_base_url)
    admin = _admin(app, mock_oidc_base_url)
    response = _configure_entra(admin)
    assert "s3cr3t-value~Xyz" not in response.text
    assert "secret" not in response.json()
    assert response.json()["configured"] is True
    # What was typed, completed with the defaults of the settings left alone.
    assert response.json()["fields"] == {
        **ENTRA_FIELDS,
        "team_selector": "groups",
        "team_attribute": "department",
    }
    assert "s3cr3t-value~Xyz" not in admin.get("/api/admin/directory/sources").text

    with app.state.session_factory() as db:
        stored = db.get(DirectoryConnectorConfig, "entra")
        assert stored.encrypted_secret
        assert "s3cr3t-value~Xyz" not in stored.encrypted_secret
        assert decrypt_secret(TEST_MASTER_KEY, stored.encrypted_secret) == "s3cr3t-value~Xyz"

    # Updating fields without a secret keeps the stored ciphertext.
    admin.put(
        "/api/admin/directory/sources/entra/config",
        json={"fields": {**ENTRA_FIELDS, "tenant_id": "contoso.onmicrosoft.com"}},
    )
    with app.state.session_factory() as db:
        kept = db.get(DirectoryConnectorConfig, "entra")
        assert decrypt_secret(TEST_MASTER_KEY, kept.encrypted_secret) == "s3cr3t-value~Xyz"

    assert admin.delete("/api/admin/directory/sources/entra/config").status_code == 204
    assert admin.post("/api/admin/directory/sync?source=entra").status_code == 409


def test_config_requires_admin_and_valid_source(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    body = {"fields": {}, "secret": "x"}
    assert operator.put("/api/admin/directory/sources/entra/config", json=body).status_code == 403
    assert signer1.put("/api/admin/directory/sources/entra/config", json=body).status_code == 403
    assert admin.put("/api/admin/directory/sources/nope/config", json=body).status_code == 404
    bad = {"fields": {"bogus": "1"}, "secret": "x"}
    assert admin.put("/api/admin/directory/sources/entra/config", json=bad).status_code == 422


def test_nested_groups_are_expanded_without_duplicates():
    from lcit_sign.services.directory.base import (
        DirectorySnapshot,
        DirGroup,
        DirUser,
        expand_nested_groups,
    )

    # All -> Sales -> Sales-EMEA ; Alice is only in Sales-EMEA.
    snapshot = DirectorySnapshot(
        groups=[
            DirGroup("all", "All", child_group_ids={"sales"}),
            DirGroup("sales", "Sales", child_group_ids={"emea"}),
            DirGroup("emea", "Sales EMEA"),
        ],
        users=[DirUser("u1", "alice@corp.test", "Alice", "A", group_ids={"emea"})],
    )
    assert expand_nested_groups(snapshot) == []
    assert snapshot.users[0].group_ids == {"emea", "sales", "all"}


def test_nested_group_cycle_is_cut_and_reported():
    from lcit_sign.services.directory.base import (
        DirectorySnapshot,
        DirGroup,
        DirUser,
        expand_nested_groups,
    )

    snapshot = DirectorySnapshot(
        groups=[
            DirGroup("a", "A", child_group_ids={"b"}),
            DirGroup("b", "B", child_group_ids={"a"}),
        ],
        users=[DirUser("u1", "bob@corp.test", "Bob", "B", group_ids={"b"})],
    )
    diagnostics = expand_nested_groups(snapshot)
    assert snapshot.users[0].group_ids == {"a", "b"}
    assert any("cycle" in line for line in diagnostics)


def test_nested_group_depth_is_limited():
    from lcit_sign.services.directory.base import (
        DirectorySnapshot,
        DirGroup,
        DirUser,
        expand_nested_groups,
    )

    groups = [DirGroup(f"g{i}", f"G{i}", child_group_ids={f"g{i + 1}"}) for i in range(30)]
    groups.append(DirGroup("g30", "G30"))
    snapshot = DirectorySnapshot(
        groups=groups, users=[DirUser("u", "c@corp.test", "C", "C", group_ids={"g30"})]
    )
    diagnostics = expand_nested_groups(snapshot, max_depth=5)
    assert len(snapshot.users[0].group_ids) == 6  # g30 + 5 ancestors
    assert any("too deep" in line for line in diagnostics)


def test_entra_sync_resolves_nested_groups(tmp_path, mock_oidc_base_url):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2/v2.0/token" in url:
            return httpx.Response(200, json={"access_token": "tok"})
        if "/users?" in url:
            return httpx.Response(200, json={"value": [
                {"id": "e1", "mail": "ann@corp.test", "givenName": "Ann", "surname": "One"}]})
        if "/groups?" in url:
            return httpx.Response(200, json={"value": [
                {"id": "parent", "displayName": "Parent"},
                {"id": "child", "displayName": "Child"}]})
        if "/groups/parent/members" in url:
            return httpx.Response(200, json={"value": [
                {"@odata.type": "#microsoft.graph.group", "id": "child"}]})
        if "/groups/child/members" in url:
            return httpx.Response(200, json={"value": [
                {"@odata.type": "#microsoft.graph.user", "id": "e1"}]})
        return httpx.Response(404)

    app = _entra_app(tmp_path, mock_oidc_base_url, handler)
    admin = _admin(app, mock_oidc_base_url)
    _configure_entra(admin)
    run = admin.post("/api/admin/directory/sync?source=entra").json()
    assert run["status"] == "SUCCESS", run
    assert run["memberships_added"] == 2
    groups = {g["name"]: g["member_count"] for g in admin.get("/api/admin/directory/groups").json()}
    assert groups == {"Parent": 1, "Child": 1}


def _entra_refuses(status: int, codes: list[int], description: str = "x"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, json={"error": "invalid_client", "error_codes": codes,
                          "error_description": description + " FAKE-SECRET-VALUE"},
        )

    return handler


def test_a_wrong_entra_secret_says_what_to_fix_and_never_echoes_anything_secret(
    tmp_path, mock_oidc_base_url
):
    handler = _entra_refuses(401, [7000215])
    app = _entra_app(tmp_path, mock_oidc_base_url, handler)
    admin = _admin(app, mock_oidc_base_url)
    _configure_entra(admin)
    run = admin.post("/api/admin/directory/sync?source=entra").json()
    assert run["status"] == "FAILED"
    assert "AADSTS7000215" in run["error"]
    assert "Valeur" in run["error"]  # points at the classic mistake: Value vs Secret ID
    assert "FAKE-SECRET-VALUE" not in run["error"] and "s3cr3t-value~Xyz" not in run["error"]


def test_each_known_entra_error_has_its_own_advice():
    from lcit_sign.services.aad_errors import describe_token_error

    def say(code):
        return describe_token_error(httpx.Response(401, json={"error_codes": [code]}))

    assert "expiré" in say(7000222)
    assert "ID de l'application" in say(700016) and "tenant" in say(700016)
    assert "tenant" in say(90002)
    assert "client public" in say(700025)
    # An unknown code still gives a useful pointer rather than a stack of jargon.
    assert "AADSTS999999" in say(999999)
    assert "identifiants refusés" in describe_token_error(httpx.Response(401, text="nope"))


def test_the_classic_entra_mix_ups_are_caught_when_typing(tmp_path, mock_oidc_base_url):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    url = "/api/admin/directory/sources/entra/config"
    secret = "abC8Q~xYzTn3kLw0pQe5vRsU9dFgHjKlMnOpQr"

    # The secret typed into the application-id field (what actually happened).
    swapped = admin.put(url, json={"fields": {**ENTRA_FIELDS, "client_id": secret}, "secret": ENTRA_FIELDS["client_id"]})  # noqa: E501
    assert swapped.status_code == 422 and "ressemble à un secret" in swapped.text
    assert secret not in swapped.text

    # An identifier (a "secret ID") given as the secret.
    as_id = admin.put(url, json={"fields": ENTRA_FIELDS, "secret": "eccc92e6-42b7-4470-8ea9-54706c4d5e54"})  # noqa: E501
    assert as_id.status_code == 422 and "Valeur" in as_id.text

    # A tenant that is neither a GUID nor a domain, an application id that is not a GUID.
    assert admin.put(url, json={"fields": {**ENTRA_FIELDS, "tenant_id": "mon tenant"}, "secret": secret}).status_code == 422  # noqa: E501
    assert admin.put(url, json={"fields": {**ENTRA_FIELDS, "client_id": "pas-un-guid"}, "secret": secret}).status_code == 422  # noqa: E501

    # Nothing wrong was stored; the right values go through.
    assert admin.get("/api/admin/directory/sources").json()[1]["configured"] is False
    assert admin.put(url, json={"fields": ENTRA_FIELDS, "secret": secret}).status_code == 200


def test_google_input_is_checked_too(tmp_path, mock_oidc_base_url):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    url = "/api/admin/directory/sources/google/config"
    good_key = json.dumps({"client_email": "sa@p.iam.gserviceaccount.com", "private_key": "-----BEGIN"})  # noqa: E501
    assert admin.put(url, json={"fields": {"admin_email": "pas une adresse"}, "secret": good_key}).status_code == 422  # noqa: E501
    assert admin.put(url, json={"fields": {"admin_email": "a@corp.test"}, "secret": "{not json"}).status_code == 422  # noqa: E501
    assert admin.put(url, json={"fields": {"admin_email": "a@corp.test"}, "secret": '{"x": 1}'}).status_code == 422  # noqa: E501
    assert admin.put(url, json={"fields": {"admin_email": "a@corp.test"}, "secret": good_key}).status_code == 200  # noqa: E501
