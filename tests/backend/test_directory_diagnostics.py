"""The connection test of the directory connectors: read-only, step by step, with codes and advice
an administrator can act on, and never a secret, a token or a provider's raw answer."""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from ldap3.core.exceptions import (
    LDAPInvalidCredentialsResult,
    LDAPSocketOpenError,
    LDAPStartTLSError,
)
from sqlalchemy import select
from test_auth_flow import login_as
from test_directory_connectors import (
    ENTRA_FIELDS,
    _admin,
    _entra_app,
    _entra_handler,
)
from test_directory_sources import BASE, _directory
from test_directory_sources import _connector as _ldap_connector

from lcit_sign.models.audit import AuditEvent
from lcit_sign.models.directory import Group, GroupMembership
from lcit_sign.models.user import User
from lcit_sign.services.directory import diagnostics, entra, google, ldap

SECRET = "s3cr3t-value~Xyz"  # noqa: S105
API = "/admin/directory/v1"


def by_name(checks):
    return {c.name: c for c in checks}


def assert_clean(checks, *needles):
    """No secret, token or private key in anything a test returns."""
    text = json.dumps([c.payload() for c in checks])
    for needle in (SECRET, "tok-abc", "gtok", "PRIVATE KEY", "Bearer", *needles):
        assert needle not in text, needle


# --- Microsoft Entra ID --------------------------------------------------------------------


def entra_connector(handler):
    return entra.EntraConnector(
        httpx.Client(transport=httpx.MockTransport(handler)),
        tenant_id=ENTRA_FIELDS["tenant_id"],
        client_id=ENTRA_FIELDS["client_id"],
        client_secret=SECRET,
    )


def graph(token=None, users=200, groups=200, members=200, error_code=None):
    """A Microsoft that answers the token, then each Graph read with the given status."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2/v2.0/token" in url:
            return token or httpx.Response(200, json={"access_token": "tok-abc"})
        status = {"/users": users, "/groups?": groups, "/members": members}
        for marker, code in status.items():
            if marker in url and not (marker == "/groups?" and "/members" in url):
                if code == 200:
                    value = {
                        "/users": [{"id": "u1"}],
                        "/groups?": [{"id": "g1"}],
                        "/members": [{"id": "u1"}],
                    }[marker]
                    return httpx.Response(200, json={"value": value})
                body = {"error": {"code": error_code or "Authorization_RequestDenied",
                                  "message": "Insufficient privileges SECRET-DETAIL"}}
                return httpx.Response(code, json=body)
        return httpx.Response(404)

    return handler


def aad(*codes, status=401):
    return httpx.Response(status, json={"error": "invalid_client", "error_codes": list(codes),
                                        "error_description": "AADSTS: raw text with detail"})


def test_entra_everything_works():
    checks = entra_connector(graph()).test_connection()
    assert [(c.name, c.status) for c in checks] == [
        ("authentication", "OK"), ("service_access", "OK"), ("users_read", "OK"),
        ("groups_read", "OK"), ("memberships_read", "OK"),
    ]
    assert diagnostics.overall(checks) == "OK"
    assert_clean(checks)


@pytest.mark.parametrize(
    ("codes", "code", "provider", "advice"),
    [
        ((7000215,), "INVALID_CREDENTIALS", "AADSTS7000215", "Valeur"),
        ((7000222,), "SECRET_EXPIRED", "AADSTS7000222", "nouveau secret"),
        ((700016,), "INVALID_CONFIGURATION", "AADSTS700016", "ID de l'application"),
        ((90002,), "TENANT_NOT_FOUND", "AADSTS90002", "ID du tenant"),
        ((900023,), "INVALID_CONFIGURATION", "AADSTS900023", "GUID"),
        ((700025,), "INVALID_CONFIGURATION", "AADSTS700025", "clients publics"),
        ((7000218,), "INVALID_CONFIGURATION", "AADSTS7000218", "secret client"),
        ((53003,), "AUTH_FAILED", "AADSTS53003", "accès conditionnel"),
        ((70011,), "INVALID_CONFIGURATION", "AADSTS70011", "permissions"),
        ((12345,), "AUTH_FAILED", "AADSTS12345", "secret client"),
    ],
)
def test_entra_token_refusals_name_the_provider_code_and_what_to_do(codes, code, provider, advice):
    checks = entra_connector(graph(token=aad(*codes))).test_connection()
    assert [c.name for c in checks] == ["authentication"]
    check = checks[0]
    assert (check.status, check.code, check.provider_code) == ("ERROR", code, provider)
    assert advice in (check.action or "")
    assert_clean(checks, "raw text with detail")


def test_entra_an_expired_secret_has_the_documented_message():
    check = entra_connector(graph(token=aad(7000222))).test_connection()[0]
    assert check.message == "Le secret client a expiré."
    assert check.action == "Créer un nouveau secret dans Entra > Certificats et secrets."


def test_entra_without_an_aadsts_code_the_http_status_is_shown():
    check = entra_connector(graph(token=httpx.Response(500))).test_connection()[0]
    assert (check.code, check.provider_code) == ("AUTH_FAILED", "HTTP 500")


def test_entra_graph_unreachable_is_the_service_not_the_login():
    def handler(request):
        if "oauth2" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok"})
        raise httpx.ConnectError("name resolution failed")

    checks = entra_connector(handler).test_connection()
    assert [(c.name, c.status, c.code) for c in checks] == [
        ("authentication", "OK", None), ("service_access", "ERROR", "NETWORK_ERROR")]


def test_entra_users_refused_but_the_rest_is_still_checked():
    checks = entra_connector(graph(users=403)).test_connection()
    named = by_name(checks)
    assert named["service_access"].status == "OK"
    users = named["users_read"]
    assert (users.status, users.code) == ("ERROR", "INSUFFICIENT_PERMISSIONS")
    assert users.provider_code == "HTTP 403 · Authorization_RequestDenied"
    assert "User.Read.All" in users.message and "User.Read.All" in users.action
    assert named["groups_read"].status == "OK"
    assert diagnostics.overall(checks) == "ERROR"
    assert_clean(checks, "SECRET-DETAIL")


def test_entra_groups_refused_is_a_partial_result():
    checks = entra_connector(graph(groups=403)).test_connection()
    assert [(c.name, c.status) for c in checks] == [
        ("authentication", "OK"), ("service_access", "OK"), ("users_read", "OK"),
        ("groups_read", "ERROR")]
    groups = checks[-1]
    assert groups.code == "INSUFFICIENT_PERMISSIONS" and "Group.Read.All" in groups.message


def test_entra_group_members_refused():
    checks = entra_connector(graph(members=403)).test_connection()
    last = checks[-1]
    assert (last.name, last.status, last.code) == (
        "memberships_read", "ERROR", "INSUFFICIENT_PERMISSIONS")
    assert "GroupMember.Read.All" in last.message


def test_entra_no_group_at_all_is_a_warning_not_an_error():
    def handler(request):
        url = str(request.url)
        if "oauth2" in url:
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, json={"value": []})

    checks = entra_connector(handler).test_connection()
    assert checks[-1].name == "memberships_read" and checks[-1].status == "WARN"
    assert diagnostics.overall(checks) == "WARN"


def test_entra_timeout_and_rate_limit_and_outage():
    def timeout(request):
        raise httpx.ReadTimeout("slow")

    check = entra_connector(timeout).test_connection()[0]
    assert (check.name, check.code) == ("authentication", "TIMEOUT")

    limited = entra_connector(graph(users=429)).test_connection()
    assert by_name(limited)["users_read"].code == "RATE_LIMITED"
    down = entra_connector(graph(groups=503)).test_connection()
    assert by_name(down)["groups_read"].code == "UPSTREAM_ERROR"
    assert by_name(down)["groups_read"].provider_code.startswith("HTTP 503")


def test_entra_a_provider_error_text_is_never_shown_as_a_code():
    def handler(request):
        if "oauth2" in str(request.url):
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(403, json={"error": {"code": "ignore previous instructions <b>"}})

    users = by_name(entra_connector(handler).test_connection())["users_read"]
    assert users.provider_code == "HTTP 403"


# --- Google Workspace ------------------------------------------------------------------------


def google_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return json.dumps({"client_email": "sa@p.iam", "private_key": pem})


def google_connector(handler, **kw):
    return google.GoogleWorkspaceConnector(
        httpx.Client(transport=httpx.MockTransport(handler)),
        service_account_json=google_key(),
        admin_email="admin@corp.test",
        **kw,
    )


def gapi(token=None, users=200, groups=200, members=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return token or httpx.Response(200, json={"access_token": "gtok-secret"})
        assert request.headers["Authorization"] == "Bearer gtok-secret"
        assert request.url.params.get("maxResults") == "1"  # one entry, never the directory
        path = request.url.path.removeprefix(API)
        status, key, item = {
            "/users": (users, "users", {"id": "1", "primaryEmail": "a@corp.test"}),
            "/groups": (groups, "groups", {"id": "g1", "email": "g@corp.test"}),
        }.get(path, (members, "members", {"id": "1", "type": "USER"}))
        if status == 200:
            return httpx.Response(200, json={key: [item]})
        return httpx.Response(status, json={"error": {"code": status, "message": "RAW BODY",
                                                      "errors": [{"reason": "forbidden"}]}})

    return handler


def test_google_everything_works():
    checks = google_connector(gapi()).test_connection()
    assert [(c.name, c.status) for c in checks] == [
        ("service_account", "OK"), ("assertion", "OK"), ("token_exchange", "OK"),
        ("delegation", "OK"), ("users_read", "OK"), ("groups_read", "OK"),
        ("memberships_read", "OK"),
    ]
    assert_clean(checks, "gtok-secret")


def test_google_an_unusable_service_account_is_refused_at_build():
    with pytest.raises(Exception, match="service account"):
        google.GoogleWorkspaceConnector(
            httpx.Client(), service_account_json="{\"client_email\": \"x\"}", admin_email="a@b.c"
        )


def test_google_unauthorized_client_means_no_domain_wide_delegation():
    response = httpx.Response(401, json={"error": "unauthorized_client",
                                         "error_description": "Client is unauthorized RAW"})
    checks = google_connector(gapi(token=response)).test_connection()
    assert [c.name for c in checks] == ["service_account", "assertion", "delegation"]
    check = checks[-1]
    assert (check.code, check.provider_code) == ("INSUFFICIENT_PERMISSIONS", "unauthorized_client")
    assert "délégation à l'échelle du domaine" in check.message
    assert_clean(checks, "RAW")


def test_google_invalid_grant_means_the_impersonated_user_or_a_delegation_not_active():
    response = httpx.Response(400, json={"error": "invalid_grant"})
    check = google_connector(gapi(token=response)).test_connection()[-1]
    assert (check.name, check.code, check.provider_code) == (
        "delegation", "INVALID_CONFIGURATION", "invalid_grant")
    assert "admin@corp.test" in check.message


@pytest.mark.parametrize("error", ["invalid_client", "invalid_request"])
def test_google_invalid_client_and_request_blame_the_key(error):
    response = httpx.Response(400, json={"error": error})
    check = google_connector(gapi(token=response)).test_connection()[-1]
    assert (check.name, check.code, check.provider_code) == (
        "token_exchange", "INVALID_CONFIGURATION", error)


@pytest.mark.parametrize(
    ("kwargs", "name", "code", "permission"),
    [
        ({"users": 403}, "users_read", "INSUFFICIENT_PERMISSIONS", "admin.directory.user"),
        ({"groups": 403}, "groups_read", "INSUFFICIENT_PERMISSIONS", "admin.directory.group."),
        ({"members": 403}, "memberships_read", "INSUFFICIENT_PERMISSIONS", "group.member"),
        ({"users": 401}, "users_read", "AUTH_FAILED", ""),
        ({"users": 429}, "users_read", "RATE_LIMITED", ""),
        ({"groups": 500}, "groups_read", "UPSTREAM_ERROR", ""),
        ({"users": 404}, "users_read", "USER_READ_FAILED", ""),
    ],
)
def test_google_reads_are_told_apart_by_status(kwargs, name, code, permission):
    checks = google_connector(gapi(**kwargs)).test_connection()
    check = by_name(checks)[name]
    assert (check.status, check.code) == ("ERROR", code)
    assert check.provider_code.startswith(f"HTTP {list(kwargs.values())[0]}")
    assert permission in (check.message + (check.action or ""))
    assert_clean(checks, "RAW BODY")


def test_google_forbidden_reason_is_kept_as_the_provider_code():
    check = by_name(google_connector(gapi(users=403)).test_connection())["users_read"]
    assert check.provider_code == "HTTP 403 · forbidden"


def test_google_timeout():
    def handler(request):
        raise httpx.ConnectTimeout("slow")

    check = google_connector(handler).test_connection()[-1]
    assert (check.name, check.code) == ("token_exchange", "TIMEOUT")


# --- LDAP ------------------------------------------------------------------------------------


def _directory_with_base():
    """The in-memory directory, with the entry the real one always has: its own base."""
    connection = _directory()
    connection.strategy.add_entry("dc=corp,dc=test", {"objectClass": "domain", "dc": "corp"})
    return connection


def ldap_connector(**overrides):
    return _ldap_connector(**{"connection_factory": _directory_with_base, **overrides})


def ldap_failing(exc):
    def factory():
        raise exc

    return ldap_connector(connection_factory=factory)


def test_ldap_everything_works():
    checks = ldap_connector().test_connection()
    assert [(c.name, c.status) for c in checks] == [
        ("bind", "OK"), ("base_dn", "OK"), ("users_query", "OK"), ("groups_query", "OK")]


def test_ldap_the_test_asks_for_one_entry_not_the_directory():
    seen = []

    def factory():
        connection = _directory_with_base()
        real = connection.search

        def search(*args, **kwargs):
            seen.append(kwargs.get("size_limit"))
            return real(*args, **kwargs)

        connection.search = search
        return connection

    ldap_connector(connection_factory=factory).test_connection()
    assert seen == [1, 1, 1]


def test_ldap_bind_refused():
    check = ldap_failing(LDAPInvalidCredentialsResult()).test_connection()[0]
    assert (check.name, check.code, check.status) == ("bind", "AUTH_FAILED", "ERROR")
    assert "DN" in check.message and check.provider_code == "LDAPInvalidCredentialsResult"


def test_ldap_certificate_not_recognised():
    exc = LDAPSocketOpenError("socket ssl wrapping error: certificate verify failed")
    check = ldap_failing(exc).test_connection()[0]
    assert (check.name, check.code) == ("tls", "TLS_ERROR")
    assert "certificat TLS n'est pas reconnu" in check.message


def test_ldap_starttls_failure_is_a_tls_error():
    check = ldap_failing(LDAPStartTLSError("tls handshake failed")).test_connection()[0]
    assert check.code == "TLS_ERROR"


def test_ldap_timeout_and_network():
    timed_out = ldap_failing(LDAPSocketOpenError("connection timed out")).test_connection()[0]
    assert (timed_out.name, timed_out.code) == ("network", "TIMEOUT")
    down = ldap_failing(LDAPSocketOpenError("unable to open socket")).test_connection()[0]
    assert (down.name, down.code) == ("network", "NETWORK_ERROR")


def test_ldap_unknown_base_dn():
    checks = ldap_connector(base_dn="dc=nowhere,dc=test").test_connection()
    last = checks[-1]
    assert (last.name, last.status, last.code) == ("base_dn", "ERROR", "BASE_DN_ERROR")
    assert [c.name for c in checks] == ["bind", "base_dn"]


def test_ldap_a_user_filter_that_fails():
    checks = ldap_connector(user_filter="(objectClass=").test_connection()
    last = checks[-1]
    assert (last.name, last.code) == ("users_query", "USER_QUERY_ERROR")
    assert "filtre des personnes" in last.message


def test_ldap_a_group_filter_that_fails_keeps_the_users_result():
    checks = ldap_connector(group_filter="(member=").test_connection()
    named = by_name(checks)
    assert named["users_query"].status == "OK"
    assert (named["groups_query"].status, named["groups_query"].code) == (
        "ERROR", "GROUP_QUERY_ERROR")


def test_ldap_empty_answers_are_warnings():
    checks = ldap_connector(
        user_filter="(uid=nobody)", group_filter="(cn=nothing)"
    ).test_connection()
    named = by_name(checks)
    assert named["users_query"].status == "WARN" and named["groups_query"].status == "WARN"
    assert diagnostics.overall(checks) == "WARN"


def test_ldap_groups_are_not_queried_when_teams_do_not_come_from_them():
    checks = ldap_connector(
        team_selector="attribute", team_attribute="department"
    ).test_connection()
    assert [c.name for c in checks] == ["bind", "base_dn", "users_query"]


# --- Through the API: administrators only, nothing written but the audit --------------------


def counts(app):
    with app.state.session_factory() as db:
        return {
            "users": sorted(
                (u.email, u.active, u.given_name, u.family_name, str(u.id))
                for u in db.execute(select(User)).scalars()
            ),
            "groups": sorted(
                (g.source, g.name, g.active, str(g.id)) for g in db.execute(select(Group)).scalars()
            ),
            "memberships": sorted(
                (str(m.user_id), str(m.group_id))
                for m in db.execute(select(GroupMembership)).scalars()
            ),
        }


def audit_actions(app, action):
    with app.state.session_factory() as db:
        return [
            e for e in db.execute(select(AuditEvent)).scalars() if e.action == action
        ]


def test_entra_test_over_the_api_changes_no_user_group_or_membership(tmp_path, mock_oidc_base_url):
    app = _entra_app(tmp_path, mock_oidc_base_url)
    admin = _admin(app, mock_oidc_base_url)
    admin.put(
        "/api/admin/directory/sources/entra/config",
        json={"fields": ENTRA_FIELDS, "secret": SECRET},
    )
    assert admin.post("/api/admin/directory/sync?source=entra").json()["status"] == "SUCCESS"
    before = counts(app)
    assert before["users"] and before["groups"] and before["memberships"]

    response = admin.post("/api/admin/directory/sources/entra/test")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "OK" and body["source"] == "entra"
    assert {c["name"] for c in body["checks"]} == {
        "authentication", "service_access", "users_read", "groups_read", "memberships_read"}
    assert set(body["checks"][0]) == {
        "name", "status", "code", "provider_code", "message", "action"}
    assert SECRET not in response.text and "tok-abc" not in response.text
    assert counts(app) == before


def test_the_test_is_audited_without_any_secret(tmp_path, mock_oidc_base_url):
    def handler(request):
        if "oauth2" in str(request.url):
            return aad(7000222)
        return _entra_handler(request)

    app = _entra_app(tmp_path, mock_oidc_base_url, handler)
    admin = _admin(app, mock_oidc_base_url)
    admin.put(
        "/api/admin/directory/sources/entra/config",
        json={"fields": ENTRA_FIELDS, "secret": SECRET},
    )
    body = admin.post("/api/admin/directory/sources/entra/test").json()
    assert body["status"] == "ERROR" and body["checks"][0]["code"] == "SECRET_EXPIRED"
    events = audit_actions(app, "DIRECTORY_CONNECTION_TESTED")
    assert len(events) == 1
    metadata = events[0].metadata_json
    assert metadata == {
        "source": "entra", "status": "ERROR", "error_code": "SECRET_EXPIRED",
        "provider_code": "AADSTS7000222",
    }
    dump = json.dumps(metadata) + str(events[0].__dict__)
    assert SECRET not in dump and "raw text" not in dump


def test_the_test_is_for_administrators_only(tmp_path, mock_oidc_base_url):
    app = _entra_app(tmp_path, mock_oidc_base_url)
    admin = _admin(app, mock_oidc_base_url)
    admin.put(
        "/api/admin/directory/sources/entra/config",
        json={"fields": ENTRA_FIELDS, "secret": SECRET},
    )
    with TestClient(app) as anonymous:
        assert anonymous.post("/api/admin/directory/sources/entra/test").status_code == 401
    # An ordinary signer is not an administrator either.
    with TestClient(app) as signer:
        login_as(signer, mock_oidc_base_url, sub="u-sales-1")
        assert signer.post("/api/admin/directory/sources/entra/test").status_code == 403


def test_the_test_needs_a_saved_connector_and_a_known_source(tmp_path, mock_oidc_base_url):
    app = _entra_app(tmp_path, mock_oidc_base_url)
    admin = _admin(app, mock_oidc_base_url)
    assert admin.post("/api/admin/directory/sources/entra/test").status_code == 409
    assert admin.post("/api/admin/directory/sources/nope/test").status_code == 404
    assert admin.post("/api/admin/directory/sources/local/test").status_code == 409


def test_the_test_is_not_a_synchronisation(tmp_path, mock_oidc_base_url):
    app = _entra_app(tmp_path, mock_oidc_base_url)
    admin = _admin(app, mock_oidc_base_url)
    admin.put(
        "/api/admin/directory/sources/entra/config",
        json={"fields": ENTRA_FIELDS, "secret": SECRET},
    )
    admin.post("/api/admin/directory/sources/entra/test")
    runs = admin.get("/api/admin/directory/sync-runs").json()
    assert runs == []


def test_google_test_over_the_api_changes_nothing(tmp_path, mock_oidc_base_url):
    app = _entra_app(tmp_path, mock_oidc_base_url, gapi())
    admin = _admin(app, mock_oidc_base_url)
    saved = admin.put(
        "/api/admin/directory/sources/google/config",
        json={"fields": {"admin_email": "admin@corp.test"}, "secret": google_key()},
    )
    assert saved.status_code == 200, saved.text
    before = counts(app)
    body = admin.post("/api/admin/directory/sources/google/test").json()
    assert body["status"] == "OK", body
    assert counts(app) == before
    assert "PRIVATE KEY" not in json.dumps(body) and "gtok" not in json.dumps(body)


def test_ldap_test_over_the_api_changes_nothing(tmp_path, mock_oidc_base_url, monkeypatch):
    app = _entra_app(tmp_path, mock_oidc_base_url)
    admin = _admin(app, mock_oidc_base_url)
    fields = {
        "server_url": "ldaps://ldap.corp.test:636",
        "bind_dn": "cn=svc,dc=corp,dc=test",
        "base_dn": BASE,
        "user_filter": "(objectClass=inetOrgPerson)",
        "group_filter": "(objectClass=groupOfNames)",
    }
    admin.put(
        "/api/admin/directory/sources/ldap/config",
        json={"fields": fields, "secret": "the-bind-password"},
    )
    real_init = ldap.LdapConnector.__init__

    def init(self, **kw):
        real_init(self, **{**kw, "connection_factory": _directory_with_base, "paged": False})

    monkeypatch.setattr(ldap.LdapConnector, "__init__", init)
    assert admin.post("/api/admin/directory/sync?source=ldap").json()["status"] == "SUCCESS"
    before = counts(app)
    response = admin.post("/api/admin/directory/sources/ldap/test")
    body = response.json()
    assert body["status"] == "OK", body
    assert "the-bind-password" not in response.text
    assert counts(app) == before


# --- Logs ------------------------------------------------------------------------------------


def test_logs_name_the_operation_and_the_code_but_hold_no_secret(caplog):
    caplog.set_level(logging.INFO)
    checks = entra_connector(graph(token=aad(7000222))).test_connection()
    for check in checks:
        diagnostics.log_check("entra", check)
    text = caplog.text
    assert "source=entra operation=authentication status=ERROR" in text
    assert "provider_code=AADSTS7000222" in text
    for forbidden in (SECRET, "tok-abc", "raw text", "Bearer"):
        assert forbidden not in text


# --- A failed synchronisation, explained ---------------------------------------------------


def test_a_failed_run_is_explained_with_its_provider_code_and_advice():
    detail = diagnostics.explain_sync_error(
        "Microsoft a refusé la connexion (AADSTS7000222) : le secret client a expiré"
    )
    assert detail["provider_code"] == "AADSTS7000222"
    assert "nouveau secret" in detail["action"]
    assert diagnostics.explain_sync_error("Erreur LDAP (LDAPSocketOpenError).") == {
        "message": "Erreur LDAP (LDAPSocketOpenError).", "provider_code": None, "action": None}
    assert diagnostics.explain_sync_error(None) is None
    forbidden = diagnostics.explain_sync_error(
        "GET https://admin.googleapis.com/x failed: Client error '403 Forbidden' for url"
    )
    assert forbidden["provider_code"] == "HTTP 403"


def test_sync_runs_carry_the_detail_and_old_plain_errors_still_read(tmp_path, mock_oidc_base_url):
    def handler(request):
        if "oauth2" in str(request.url):
            return aad(7000222)
        return _entra_handler(request)

    app = _entra_app(tmp_path, mock_oidc_base_url, handler)
    admin = _admin(app, mock_oidc_base_url)
    admin.put(
        "/api/admin/directory/sources/entra/config",
        json={"fields": ENTRA_FIELDS, "secret": SECRET},
    )
    run = admin.post("/api/admin/directory/sync?source=entra").json()
    assert run["status"] == "FAILED"
    assert run["error_detail"]["provider_code"] == "AADSTS7000222"
    assert run["error_detail"]["message"] == run["error"]
    ok_run = {"error": None}
    assert diagnostics.explain_sync_error(ok_run["error"]) is None


# --- A synchronisation that fails still touches nothing -----------------------------------


def test_google_sync_failure_touches_nothing_and_says_why(tmp_path, mock_oidc_base_url):
    from test_google_directory_http import FakeGoogle

    state = {"broken": False}
    healthy = FakeGoogle()

    def handler(request: httpx.Request) -> httpx.Response:
        if state["broken"] and request.url.host == "oauth2.googleapis.com":
            return httpx.Response(401, json={"error": "unauthorized_client"})
        return healthy(request)

    app = _entra_app(tmp_path, mock_oidc_base_url, handler)
    admin = _admin(app, mock_oidc_base_url)
    admin.put(
        "/api/admin/directory/sources/google/config",
        json={"fields": {"admin_email": "admin@corp.test"}, "secret": google_key()},
    )
    assert admin.post("/api/admin/directory/sync?source=google").json()["status"] == "SUCCESS"
    before = counts(app)
    assert before["users"] and before["memberships"]
    state["broken"] = True
    run = admin.post("/api/admin/directory/sync?source=google").json()
    assert run["status"] == "FAILED"
    assert run["error_detail"]["provider_code"] == "unauthorized_client"
    assert "délégation" in run["error_detail"]["action"]
    assert counts(app) == before


def test_ldap_sync_failure_touches_nothing(tmp_path, mock_oidc_base_url, monkeypatch):
    state = {"broken": False}

    def factory():
        if state["broken"]:
            raise LDAPSocketOpenError("unable to open socket")
        return _directory_with_base()

    app = _entra_app(tmp_path, mock_oidc_base_url)
    admin = _admin(app, mock_oidc_base_url)
    admin.put(
        "/api/admin/directory/sources/ldap/config",
        json={
            "fields": {
                "server_url": "ldaps://ldap.corp.test:636",
                "bind_dn": "cn=svc,dc=corp,dc=test",
                "base_dn": BASE,
                "user_filter": "(objectClass=inetOrgPerson)",
                "group_filter": "(objectClass=groupOfNames)",
            },
            "secret": "the-bind-password",
        },
    )
    real_init = ldap.LdapConnector.__init__

    def init(self, **kw):
        real_init(self, **{**kw, "connection_factory": factory, "paged": False})

    monkeypatch.setattr(ldap.LdapConnector, "__init__", init)
    assert admin.post("/api/admin/directory/sync?source=ldap").json()["status"] == "SUCCESS"
    before = counts(app)
    state["broken"] = True
    run = admin.post("/api/admin/directory/sync?source=ldap").json()
    assert run["status"] == "FAILED" and run["error"]
    assert counts(app) == before
    # The connection test says the same thing as the failed run, with a code.
    test = admin.post("/api/admin/directory/sources/ldap/test").json()
    assert test["status"] == "ERROR" and test["checks"][0]["code"] == "NETWORK_ERROR"
    assert counts(app) == before
