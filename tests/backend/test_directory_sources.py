"""Each directory connector in its own module: what it describes, how it reads teams,
and the LDAP one (against an in-memory directory)."""

from __future__ import annotations

import json

import httpx
import pytest
from ldap3 import MOCK_SYNC, Connection, Server
from sqlalchemy import select
from test_directory_connectors import ENTRA_FIELDS, _admin, _entra_app

from lcit_sign.models.directory import Group
from lcit_sign.services.directory import entra, google, ldap
from lcit_sign.services.directory.base import DirectoryConnectorError
from lcit_sign.services.directory.registry import SPECS


def test_every_connector_describes_its_settings_with_a_help_bubble_each(
    tmp_path, mock_oidc_base_url
):
    assert set(SPECS) == {"entra", "google", "ldap"}
    admin = _admin(_entra_app(tmp_path, mock_oidc_base_url), mock_oidc_base_url)
    listed = {s["source"]: s for s in admin.get("/api/admin/directory/sources").json()}
    for source in SPECS:
        spec = listed[source]["spec"]
        assert spec["label"] and spec["description"]
        for field in [*spec["fields"], spec["secret"]]:
            assert field["label"] and len(field["help"]) > 20, (source, field["name"])
        # Every connector says where the team name comes from.
        assert "team_selector" in {f["name"] for f in spec["fields"]}


def test_google_explains_how_to_prepare_it_step_by_step(tmp_path, mock_oidc_base_url):
    admin = _admin(_entra_app(tmp_path, mock_oidc_base_url), mock_oidc_base_url)
    listed = {s["source"]: s.get("spec") for s in admin.get("/api/admin/directory/sources").json()}
    steps = listed["google"]["guide"]
    text = " ".join(steps)
    assert len(steps) >= 6
    # The three read-only scopes the delegation must carry, and the key the admin pastes.
    for scope in (
        "directory.user.readonly",
        "directory.group.readonly",
        "directory.group.member.readonly",
    ):
        assert scope in text
    assert "Admin SDK API" in text and "unauthorized_client" in text
    assert listed["entra"]["guide"] == []


# --- Entra: teams from an attribute ---------------------------------------------------


def _entra_departments(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "oauth2/v2.0/token" in url:
        return httpx.Response(200, json={"access_token": "tok"})
    if "/users?" in url:
        assert "department" in url  # the attribute asked for is the one read
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "e1",
                        "mail": "a@corp.test",
                        "givenName": "A",
                        "surname": "One",
                        "department": "Comptabilité",
                        "accountEnabled": True,
                    },
                    {
                        "id": "e2",
                        "mail": "b@corp.test",
                        "givenName": "B",
                        "surname": "Two",
                        "department": "Comptabilité",
                        "accountEnabled": True,
                    },
                    {
                        "id": "e3",
                        "mail": "c@corp.test",
                        "givenName": "C",
                        "surname": "Three",
                        "department": "RH",
                        "accountEnabled": True,
                    },
                    {
                        "id": "e4",
                        "mail": "d@corp.test",
                        "givenName": "D",
                        "surname": "Four",
                        "accountEnabled": True,
                    },  # no department: in no team
                ]
            },
        )
    if "/groups" in url:
        raise AssertionError("groups must not be read when teams come from an attribute")
    return httpx.Response(404)


def test_entra_teams_can_come_from_the_department_instead_of_the_groups(
    tmp_path, mock_oidc_base_url
):
    app = _entra_app(tmp_path, mock_oidc_base_url, _entra_departments)
    admin = _admin(app, mock_oidc_base_url)
    saved = admin.put(
        "/api/admin/directory/sources/entra/config",
        json={
            "fields": {
                **ENTRA_FIELDS,
                "team_selector": "attribute",
                "team_attribute": "department",
            },
            "secret": "s3cr3t-value~Xyz",
        },
    )
    assert saved.status_code == 200, saved.text
    run = admin.post("/api/admin/directory/sync?source=entra").json()
    assert run["status"] == "SUCCESS", run
    teams = {g["name"]: g["member_count"] for g in admin.get("/api/admin/directory/groups").json()}
    assert teams == {"Comptabilité": 2, "RH": 1}


def test_entra_refuses_an_attribute_it_does_not_know_and_a_missing_one():
    with pytest.raises(DirectoryConnectorError):
        entra.EntraConnector(
            httpx.Client(),
            tenant_id="t",
            client_id="c",
            client_secret="s",
            team_selector="attribute",
            team_attribute="displayName,mail",
        )
    with pytest.raises(ValueError, match="attribut"):
        entra.validate({**ENTRA_FIELDS, "team_selector": "attribute", "team_attribute": ""}, None)


# --- Google: organisational units and departments ---------------------------------


def _google_connector(selector, attribute, handler):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

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


def _google_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "token" in url:
        return httpx.Response(200, json={"access_token": "tok"})
    if "/users" in url:
        return httpx.Response(
            200,
            json={
                "users": [
                    {
                        "id": "1",
                        "primaryEmail": "A@corp.test",
                        "name": {"givenName": "A", "familyName": "X"},
                        "orgUnitPath": "/Finance/Achats",
                        "organizations": [{"department": "Achats"}],
                    },
                    {
                        "id": "2",
                        "primaryEmail": "b@corp.test",
                        "name": {"givenName": "B", "familyName": "Y"},
                        "orgUnitPath": "/Finance/Achats",
                        "organizations": [{"department": "Achats"}],
                    },
                    {
                        "id": "3",
                        "primaryEmail": "c@corp.test",
                        "name": {"givenName": "C", "familyName": "Z"},
                        "orgUnitPath": "/",
                        "organizations": [],
                    },
                ]
            },
        )
    raise AssertionError(f"unexpected call {url}")


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [("orgunit", {"Finance / Achats": 2}), ("department", {"Achats": 2})],
)
def test_google_teams_from_the_org_unit_or_the_department(attribute, expected):
    snapshot = _google_connector("attribute", attribute, _google_handler).fetch()
    assert {
        g.name: sum(g.external_id in u.group_ids for u in snapshot.users) for g in snapshot.groups
    } == expected


# --- LDAP ----------------------------------------------------------------------------

BASE = "dc=corp,dc=test"


def _directory() -> Connection:
    server = Server("fake-ldap")
    connection = Connection(
        server, user="cn=svc,dc=corp,dc=test", password="pw", client_strategy=MOCK_SYNC
    )
    people = [
        (
            "uid=ann,ou=Comptabilite,ou=People,dc=corp,dc=test",
            "ann",
            "Ann",
            "One",
            "ann@corp.test",
            "Comptabilite-dept",
            512,
        ),
        (
            "uid=bob,ou=Comptabilite,ou=People,dc=corp,dc=test",
            "bob",
            "Bob",
            "Two",
            "bob@corp.test",
            "Comptabilite-dept",
            514,
        ),  # AD: bit 2 = disabled
        (
            "uid=cy,ou=RH,ou=People,dc=corp,dc=test",
            "cy",
            "Cy",
            "Three",
            "cy@corp.test",
            "RH-dept",
            512,
        ),
    ]
    connection.strategy.add_entry(
        "cn=svc,dc=corp,dc=test", {"userPassword": "pw", "objectClass": "person"}
    )
    for dn, uid, given, family, mail, department, uac in people:
        connection.strategy.add_entry(
            dn,
            {
                "objectClass": ["person", "inetOrgPerson"],
                "uid": uid,
                "givenName": given,
                "sn": family,
                "cn": f"{given} {family}",
                "mail": mail,
                "department": department,
                "userAccountControl": str(uac),
                "entryUUID": f"uuid-{uid}",
            },
        )
    connection.strategy.add_entry(
        "cn=Finance,ou=Groups,dc=corp,dc=test",
        {
            "objectClass": "groupOfNames",
            "cn": "Finance",
            "description": "Money",
            "member": [
                "uid=ann,ou=Comptabilite,ou=People,dc=corp,dc=test",
                "uid=bob, ou=Comptabilite, ou=People, dc=corp, dc=test",  # spaces, same DN
                "cn=Direction,ou=Groups,dc=corp,dc=test",
            ],
        },
    )
    connection.strategy.add_entry(
        "cn=Direction,ou=Groups,dc=corp,dc=test",
        {
            "objectClass": "groupOfNames",
            "cn": "Direction",
            "member": ["uid=cy,ou=RH,ou=People,dc=corp,dc=test"],
        },
    )
    connection.bind()
    return connection


def _connector(**overrides):
    settings = {
        "server_url": "ldaps://ldap.corp.test:636",
        "bind_dn": "cn=svc,dc=corp,dc=test",
        "bind_password": "pw",
        "base_dn": BASE,
        "user_filter": "(objectClass=inetOrgPerson)",
        "group_filter": "(objectClass=groupOfNames)",
        "team_selector": "groups",
        "connection_factory": _directory,
        "paged": False,
        **overrides,
    }
    return ldap.LdapConnector(**settings)


def test_ldap_reads_people_groups_and_nested_groups():
    snapshot = _connector().fetch()
    users = {u.email: u for u in snapshot.users}
    assert set(users) == {"ann@corp.test", "bob@corp.test", "cy@corp.test"}
    assert (users["ann@corp.test"].given_name, users["ann@corp.test"].family_name) == ("Ann", "One")
    assert users["ann@corp.test"].active is True
    assert users["bob@corp.test"].active is False  # the directory flags the account disabled
    groups = {g.name: g for g in snapshot.groups}
    assert set(groups) == {"Finance", "Direction"}
    # A member written with other spaces is still the same person; a group inside a group is kept.
    assert {u.email for u in snapshot.users if groups["Finance"].external_id in u.group_ids} == {
        "ann@corp.test",
        "bob@corp.test",
    }
    assert groups["Direction"].external_id in groups["Finance"].child_group_ids


def test_ldap_team_can_be_an_attribute_or_the_container_of_the_person():
    by_attribute = _connector(team_selector="attribute", team_attribute="department").fetch()
    assert {g.name for g in by_attribute.groups} == {"Comptabilite-dept", "RH-dept"}

    by_container = _connector(team_selector="container", group_filter="").fetch()
    teams = {
        g.name: sum(g.external_id in u.group_ids for u in by_container.users)
        for g in by_container.groups
    }
    assert teams == {"Comptabilite": 2, "RH": 1}

    both = _connector(team_selector="both", team_attribute="department").fetch()
    assert {g.name for g in both.groups} == {"Finance", "Direction", "Comptabilite-dept", "RH-dept"}


def test_ldap_a_person_without_mail_is_skipped_and_groups_can_be_left_out():
    snapshot = _connector(email_attribute="doesNotExist", group_filter="").fetch()
    assert snapshot.users == [] and snapshot.groups == []


def test_ldap_form_checks_what_would_leak_or_never_work():
    ok = {
        "server_url": "ldaps://ldap.corp.test:636",
        "start_tls": "no",
        "bind_dn": "cn=svc,dc=corp,dc=test",
        "base_dn": BASE,
        "team_selector": "attribute",
        "team_attribute": "department",
        "group_filter": "",
    }
    ldap.validate(ok, "pw")
    # The service account's password must not travel in clear.
    with pytest.raises(ValueError, match="en clair"):
        ldap.validate({**ok, "server_url": "ldap://ldap.corp.test:389"}, "pw")
    ldap.validate({**ok, "server_url": "ldap://ldap.corp.test:389", "start_tls": "yes"}, "pw")
    with pytest.raises(ValueError, match="ldaps://"):
        ldap.validate({**ok, "server_url": "http://ldap.corp.test"}, "pw")
    with pytest.raises(ValueError, match="DN"):
        ldap.validate({**ok, "bind_dn": "svc"}, "pw")
    with pytest.raises(ValueError, match="parenthèses"):
        ldap.validate({**ok, "user_filter": "objectClass=person"}, "pw")
    with pytest.raises(ValueError, match="attribut"):
        ldap.validate({**ok, "team_attribute": ""}, "pw")
    with pytest.raises(ValueError, match="filtre des groupes"):
        ldap.validate({**ok, "team_selector": "groups"}, "pw")
    # A cloud metadata address is never a directory server.
    with pytest.raises(ValueError, match="refusé"):
        ldap.validate({**ok, "server_url": "ldaps://169.254.169.254:636"}, "pw")


def test_ldap_is_configured_and_synced_through_the_admin_api(
    tmp_path, mock_oidc_base_url, monkeypatch
):
    app = _entra_app(tmp_path, mock_oidc_base_url)
    admin = _admin(app, mock_oidc_base_url)
    fields = {
        "server_url": "ldaps://ldap.corp.test:636",
        "bind_dn": "cn=svc,dc=corp,dc=test",
        "base_dn": BASE,
        "user_filter": "(objectClass=inetOrgPerson)",
        "group_filter": "(objectClass=groupOfNames)",
    }
    saved = admin.put(
        "/api/admin/directory/sources/ldap/config",
        json={"fields": fields, "secret": "the-bind-password"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["fields"]["team_selector"] == "groups"  # the default, filled in
    assert "the-bind-password" not in saved.text

    # Without a real server: the connector built from the stored settings reads our directory.
    real_init = ldap.LdapConnector.__init__

    def init(self, **kw):
        real_init(self, **{**kw, "connection_factory": _directory, "paged": False})

    monkeypatch.setattr(ldap.LdapConnector, "__init__", init)
    run = admin.post("/api/admin/directory/sync?source=ldap").json()
    assert run["status"] == "SUCCESS", run
    assert run["users_added"] == 3 and run["groups_added"] == 2
    with app.state.session_factory() as db:
        assert {
            g.name for g in db.execute(select(Group).where(Group.source == "ldap")).scalars()
        } == {"Finance", "Direction"}
