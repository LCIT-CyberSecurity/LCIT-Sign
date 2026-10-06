"""Google Workspace directory: the exact HTTP the connector sends. The fake Google is strict — a
parameter an endpoint does not take, or a missing one, fails the test, as the real API would refuse
or ignore it."""

from __future__ import annotations

import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from lcit_sign.services.directory import google
from lcit_sign.services.directory.base import DirectoryConnectorError

API = "/admin/directory/v1"
# What each endpoint takes: (required, allowed). members.list takes no `customer`.
USERS = ({"maxResults": "200", "customer": "my_customer"}, {"pageToken", "projection"})
GROUPS = ({"maxResults": "200", "customer": "my_customer"}, {"pageToken"})
MEMBERS = ({"maxResults": "200"}, {"pageToken"})


def _connector(handler, selector="groups", attribute="orgunit"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return google.GoogleWorkspaceConnector(
        httpx.Client(transport=httpx.MockTransport(handler)),
        service_account_json=json.dumps({"client_email": "sa@p.iam", "private_key": pem}),
        admin_email="admin@corp.test",
        team_selector=selector,
        team_attribute=attribute,
    )


class FakeGoogle:
    """Two pages of everything; records the calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def _strict(self, path: str, params: dict[str, str], spec) -> None:
        required, optional = spec
        for name, value in required.items():
            assert params.get(name) == value, f"{path}: {name} should be {value!r}: {params}"
        extra = set(params) - set(required) - optional
        assert not extra, f"{path}: parameter(s) this endpoint does not take: {sorted(extra)}"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "gtok"})
        assert request.headers["Authorization"] == "Bearer gtok"
        params = dict(url.params)
        self.calls.append((url.path, params))
        page = params.get("pageToken")
        path = url.path.removeprefix(API)
        if path == "/users":
            self._strict(path, params, USERS)
            if page is None:
                return httpx.Response(200, json={"nextPageToken": "u2", "users": [
                    _user("1", "ann@corp.test", "Ann"), _user("2", "bob@corp.test", "Bob")]})
            return httpx.Response(200, json={"users": [
                _user("3", "cy@corp.test", "Cy", suspended=True)]})
        if path == "/groups":
            self._strict(path, params, GROUPS)
            if page is None:
                return httpx.Response(200, json={"nextPageToken": "g2", "groups": [
                    {"id": "g1", "name": "Compta", "email": "compta@corp.test"}]})
            return httpx.Response(200, json={"groups": [
                {"id": "g2", "name": "Tous", "email": "tous@corp.test", "description": "Everyone"}]})
        if path.startswith("/groups/") and path.endswith("/members"):
            self._strict(path, params, MEMBERS)
            group = path.split("/")[2]
            if group == "g1" and page is None:
                return httpx.Response(200, json={"nextPageToken": "m2", "members": [
                    {"id": "1", "type": "USER"}]})
            if group == "g1":
                return httpx.Response(200, json={"members": [
                    {"id": "3", "type": "USER"}, {"id": "outsider", "type": "USER"}]})
            return httpx.Response(200, json={"members": [{"id": "g1", "type": "GROUP"},
                                                         {"id": "2", "type": "USER"}]})
        pytest.fail(f"unexpected call {request.url}")


def _user(uid: str, email: str, name: str, suspended: bool = False) -> dict:
    return {"id": uid, "primaryEmail": email, "suspended": suspended,
            "name": {"givenName": name, "familyName": "X"}, "orgUnitPath": "/Finance"}


def test_every_list_is_paged_with_the_parameters_its_endpoint_takes():
    fake = FakeGoogle()
    snapshot = _connector(fake).fetch()
    paths = [(path.removeprefix(API), params.get("pageToken")) for path, params in fake.calls]
    assert paths == [
        ("/users", None), ("/users", "u2"),
        ("/groups", None),
        ("/groups/g1/members", None), ("/groups/g1/members", "m2"),
        ("/groups", "g2"),
        ("/groups/g2/members", None),
    ]
    assert sorted(u.email for u in snapshot.users) == ["ann@corp.test", "bob@corp.test", "cy@corp.test"]


def test_members_are_users_or_nested_groups_and_strangers_are_ignored():
    snapshot = _connector(FakeGoogle()).fetch()
    users = {u.external_id: u for u in snapshot.users}
    groups = {g.external_id: g for g in snapshot.groups}
    assert users["1"].group_ids == {"g1"}
    assert users["3"].group_ids == {"g1"}  # on the second page of members
    assert users["2"].group_ids == {"g2"}
    assert groups["g2"].child_group_ids == {"g1"}  # a group inside a group
    assert groups["g2"].description == "Everyone"
    assert all("outsider" not in u.group_ids for u in snapshot.users)


def test_a_suspended_user_is_inactive():
    users = {u.external_id: u for u in _connector(FakeGoogle()).fetch().users}
    assert users["3"].active is False
    assert users["1"].active is True


def test_the_department_projection_is_asked_of_users_only():
    fake = FakeGoogle()
    _connector(fake, selector="attribute", attribute="department").fetch()
    users_calls = [p for path, p in fake.calls if path.endswith("/users")]
    assert users_calls and all(p.get("projection") == "full" for p in users_calls)
    assert not any(path.endswith("/groups") for path, _ in fake.calls)  # no groups asked


def test_a_google_error_is_reported_in_words():
    def refusing(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "gtok"})
        return httpx.Response(403, json={"error": {"code": 403, "message": "Not Authorized"}})

    with pytest.raises(DirectoryConnectorError):
        _connector(refusing).fetch()
