"""Real accounts (Entra, Google, LDAP) behind the mock SSO: what the sign-in page offers, where
codes may go, and each way of signing in."""

from __future__ import annotations

import base64
import json
import os
from urllib.parse import parse_qs, urlparse

# Same values as conftest's mock-OIDC fixture, set before the mock app is first imported: the
# module reads them once, and the other tests share that import.
os.environ.setdefault("MOCK_OIDC_ISSUER", "http://127.0.0.1:8099")
os.environ.setdefault("MOCK_OIDC_PUBLIC_BASE_URL", "http://127.0.0.1:8099")

import httpx
import pytest
import real_providers as providers
from app import app
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from fastapi.testclient import TestClient
from ldap3 import MOCK_SYNC, Connection, Server

APP_CALLBACK = "https://sign.corp.test/api/auth/callback"
PUBLIC = os.environ["MOCK_OIDC_PUBLIC_BASE_URL"]
VERIFIER = "v" * 60
CHALLENGE = create_s256_code_challenge(VERIFIER)
ENTRA = {
    "tenant_id": "73405479-f042-45d7-8149-c90341261b65",
    "client_id": "333a1a3e-1d45-4661-9c9e-2c91d7b0c5d3",
    "client_secret": "s3cret~value",
}
GOOGLE = {
    "client_id": "g-client.apps.googleusercontent.com",
    "client_secret": "g-secret",
    "allowed_domain": "corp.test",
}
LDAP = {
    "server_url": "ldaps://ldap.corp.test:636",
    "bind_dn": "cn=svc,dc=corp,dc=test",
    "bind_password": "svc-pw",
    "base_dn": "dc=corp,dc=test",
}


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    providers._states.clear()
    providers._ldap_attempts.clear()
    monkeypatch.setenv("MOCK_OIDC_PROVIDERS_FILE", str(tmp_path / "none.json"))
    monkeypatch.delenv("MOCK_OIDC_ALLOWED_REDIRECTS", raising=False)
    monkeypatch.setattr(providers, "ldap_connect", None)


def configure(monkeypatch, tmp_path, config, allowed=APP_CALLBACK):
    path = tmp_path / "providers.json"
    path.write_text(json.dumps(config))
    monkeypatch.setenv("MOCK_OIDC_PROVIDERS_FILE", str(path))
    if allowed:
        monkeypatch.setenv("MOCK_OIDC_ALLOWED_REDIRECTS", allowed)


def authorize_params(redirect=APP_CALLBACK, state="app-state"):
    return {
        "client_id": "lcit-sign",
        "redirect_uri": redirect,
        "state": state,
        "nonce": "app-nonce",
        "code_challenge": CHALLENGE,
    }


client = TestClient(app, follow_redirects=False)


def exchange(code: str, redirect=APP_CALLBACK) -> dict:
    response = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": "lcit-sign",
            "client_secret": "x",
            "code_verifier": VERIFIER,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()["id_token"].split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def code_from(response) -> tuple[str, dict]:
    assert response.status_code in (302, 307), response.text
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query["code"][0], query


def unsigned_id_token(claims: dict) -> str:
    def b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64(claims)}.x"


def nonce_of(state_token: str) -> str:
    return providers._states[state_token]["nonce"]


def fake_provider(monkeypatch, claims, status=200):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["form"] = parse_qs(request.content.decode())
        if status != 200:
            return httpx.Response(status, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"id_token": unsigned_id_token(claims)})

    monkeypatch.setattr(
        providers, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    return seen


# --- the sign-in page --------------------------------------------------------------------


def test_without_real_providers_nothing_changes_and_the_page_says_so():
    page = client.get("/authorize", params=authorize_params()).text
    assert "Alice" in page and "non configuré sur ce serveur" in page
    assert "Se connecter avec" not in page and 'type="password"' not in page


def test_configured_providers_are_offered_next_to_the_test_identities(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, {"entra": ENTRA, "google": GOOGLE, "ldap": LDAP})
    page = client.get("/authorize", params=authorize_params()).text
    assert "Alice" in page
    assert "Se connecter avec Microsoft Entra ID" in page and "Se connecter avec Google" in page
    assert 'action="login/ldap"' in page and 'type="password"' in page
    assert "s3cret~value" not in page and "svc-pw" not in page  # secrets never reach the page


def test_a_provider_missing_a_setting_is_not_offered(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, {"entra": {"tenant_id": "t", "client_id": "c"}})
    assert (
        "Se connecter avec Microsoft"
        not in client.get("/authorize", params=authorize_params()).text
    )


def test_codes_only_go_where_the_app_allows(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, {"entra": ENTRA})
    evil = authorize_params(redirect="https://evil.test/steal")
    assert client.get("/authorize", params=evil).status_code == 400
    assert client.get("/authorize/choose", params={**evil, "sub": "u-it-1"}).status_code == 400
    assert client.get("/login/entra", params=evil).status_code == 400
    assert client.get("/authorize", params=authorize_params()).status_code == 200


def test_real_accounts_are_refused_when_no_allow_list_is_set(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, {"entra": ENTRA}, allowed=None)
    assert client.get("/login/entra", params=authorize_params()).status_code == 400
    assert (
        "Se connecter avec Microsoft"
        not in client.get("/authorize", params=authorize_params()).text
    )
    # The test identities still work as before.
    choose = client.get("/authorize/choose", params={**authorize_params(), "sub": "u-it-1"})
    assert code_from(choose)[0]


# --- Entra / Google ----------------------------------------------------------------------


def test_entra_sends_the_person_to_microsoft_and_back_signed_in(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, {"entra": ENTRA})
    go = client.get("/login/entra", params=authorize_params())
    target = urlparse(go.headers["location"])
    assert target.netloc == "login.microsoftonline.com"
    assert target.path == f"/{ENTRA['tenant_id']}/oauth2/v2.0/authorize"
    query = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert query["client_id"] == ENTRA["client_id"] and query["code_challenge_method"] == "S256"
    assert query["scope"] == "openid profile email"
    assert query["redirect_uri"] == f"{PUBLIC}/callback/entra"
    assert "client_secret" not in target.query

    seen = fake_provider(
        monkeypatch,
        {
            "aud": ENTRA["client_id"],
            "nonce": nonce_of(query["state"]),
            "oid": "oid-123",
            "preferred_username": "Cedric.DiCesare@eunoia-security.com",
            "name": "Cédric Di Cesare",
        },
    )
    back = client.get("/callback/entra", params={"code": "ms-code", "state": query["state"]})
    code, returned = code_from(back)
    assert returned["state"] == ["app-state"]  # the app's own state, not ours
    assert urlparse(back.headers["location"]).geturl().startswith(APP_CALLBACK)
    # The provider was asked with our secret and our verifier, from the back channel.
    assert seen["form"]["client_secret"] == ["s3cret~value"] and seen["form"]["code"] == ["ms-code"]
    claims = exchange(code)
    assert claims["email"] == "cedric.dicesare@eunoia-security.com"
    assert claims["sub"] == "entra:oid-123" and claims["nonce"] == "app-nonce"
    assert (claims["given_name"], claims["family_name"]) == ("Cédric", "Di Cesare")


def test_a_provider_answer_is_used_once_and_only_if_it_fits(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, {"entra": ENTRA})
    go = client.get("/login/entra", params=authorize_params())
    state = parse_qs(urlparse(go.headers["location"]).query)["state"][0]
    fake_provider(
        monkeypatch,
        {"aud": "another-app", "nonce": nonce_of(state), "preferred_username": "a@b.test"},
    )
    refused = client.get("/callback/entra", params={"code": "c", "state": state})
    assert refused.status_code == 400 and "incohérente" in refused.text
    # The state is spent: replaying it, or inventing one, gets nothing.
    assert client.get("/callback/entra", params={"code": "c", "state": state}).status_code == 400
    assert (
        client.get("/callback/entra", params={"code": "c", "state": "made-up"}).status_code == 400
    )
    # Cancelled at the provider.
    assert client.get("/callback/entra", params={"error": "access_denied"}).status_code == 400


def test_a_provider_that_refuses_the_code_is_reported_without_leaking(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, {"entra": ENTRA})
    go = client.get("/login/entra", params=authorize_params())
    state = parse_qs(urlparse(go.headers["location"]).query)["state"][0]
    fake_provider(monkeypatch, {}, status=400)
    failed = client.get("/callback/entra", params={"code": "c", "state": state})
    assert failed.status_code == 400 and "refusé" in failed.text and "s3cret" not in failed.text


def test_google_only_accepts_the_configured_domain(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, {"google": GOOGLE})

    def sign_in(email):
        go = client.get("/login/google", params=authorize_params())
        target = parse_qs(urlparse(go.headers["location"]).query)
        assert target["hd"] == ["corp.test"]
        fake_provider(
            monkeypatch,
            {
                "aud": GOOGLE["client_id"],
                "nonce": nonce_of(target["state"][0]),
                "sub": "g-1",
                "email": email,
                "email_verified": True,
                "given_name": "Ann",
                "family_name": "One",
            },
        )
        return client.get("/callback/google", params={"code": "c", "state": target["state"][0]})

    assert exchange(code_from(sign_in("ann@corp.test"))[0])["sub"] == "google:g-1"
    outsider = sign_in("ann@gmail.com")
    assert outsider.status_code == 400 and "@corp.test" in outsider.text


# --- LDAP ------------------------------------------------------------------------------


@pytest.fixture
def ldap_directory(monkeypatch):
    server = Server("fake-ldap")
    seed = Connection(
        server, user="cn=svc,dc=corp,dc=test", password="svc-pw", client_strategy=MOCK_SYNC
    )
    seed.strategy.add_entry(
        "cn=svc,dc=corp,dc=test", {"userPassword": "svc-pw", "objectClass": "person"}
    )
    for uid, mail in (("ann", "ann@corp.test"), ("nomail", "")):
        seed.strategy.add_entry(
            f"uid={uid},ou=People,dc=corp,dc=test",
            {
                "objectClass": ["person", "inetOrgPerson"],
                "uid": uid,
                "cn": uid.title(),
                "sn": "One",
                "givenName": uid.title(),
                "userPassword": "ann-pw",
                "entryUUID": f"u-{uid}",
                **({"mail": mail} if mail else {}),
            },
        )

    def connect(dn, password):
        return Connection(server, user=dn, password=password, client_strategy=MOCK_SYNC)

    monkeypatch.setattr(providers, "ldap_connect", connect)


def ldap_post(login, password, redirect=APP_CALLBACK):
    return client.post(
        "/login/ldap", data={**authorize_params(redirect), "login": login, "password": password}
    )


def test_ldap_signs_in_with_the_directory_password_and_forgets_it(
    monkeypatch, tmp_path, ldap_directory
):
    configure(monkeypatch, tmp_path, {"ldap": LDAP})
    ok = ldap_post("ann", "ann-pw")
    claims = exchange(code_from(ok)[0])
    assert claims["email"] == "ann@corp.test" and claims["sub"] == "ldap:u-ann"
    assert "ann-pw" not in json.dumps(claims)


def test_ldap_gives_the_same_answer_for_a_wrong_password_and_an_unknown_login(
    monkeypatch, tmp_path, ldap_directory
):
    configure(monkeypatch, tmp_path, {"ldap": LDAP})
    wrong, unknown = ldap_post("ann", "nope"), ldap_post("ghost", "ann-pw")
    for response in (wrong, unknown):
        assert response.status_code == 401
        assert "Identifiant ou mot de passe incorrect." in response.text
        assert "ann-pw" not in response.text and "nope" not in response.text
        assert "location" not in response.headers


def test_ldap_never_accepts_an_empty_password_or_a_filter_trick(
    monkeypatch, tmp_path, ldap_directory
):
    configure(monkeypatch, tmp_path, {"ldap": LDAP})
    assert ldap_post("ann", "").status_code in (401, 422)  # an empty password is an anonymous bind
    assert ldap_post("*", "ann-pw").status_code == 401
    assert ldap_post("*)(uid=*", "ann-pw").status_code == 401
    assert ldap_post("ann)(|(uid=*", "ann-pw").status_code == 401


def test_ldap_refuses_an_account_without_mail(monkeypatch, tmp_path, ldap_directory):
    configure(monkeypatch, tmp_path, {"ldap": LDAP})
    refused = ldap_post("nomail", "ann-pw")
    assert refused.status_code == 429 and "adresse e-mail" in refused.text


def test_ldap_attempts_are_limited(monkeypatch, tmp_path, ldap_directory):
    configure(monkeypatch, tmp_path, {"ldap": LDAP})
    for _ in range(providers.LDAP_ATTEMPTS):
        assert ldap_post("ann", "wrong").status_code == 401
    blocked = ldap_post("ann", "ann-pw")
    assert blocked.status_code == 429 and "Trop d" in blocked.text and "essais" in blocked.text
    assert "location" not in blocked.headers


def test_ldap_codes_only_go_to_the_app(monkeypatch, tmp_path, ldap_directory):
    configure(monkeypatch, tmp_path, {"ldap": LDAP})
    assert ldap_post("ann", "ann-pw", redirect="https://evil.test/x").status_code == 400


def test_an_entra_guest_is_recognised_by_their_real_address(monkeypatch, tmp_path):
    """An invited person's sign-in name is `bob_gmail.com#EXT#@tenant…`: matched on the address."""
    configure(monkeypatch, tmp_path, {"entra": ENTRA})
    go = client.get("/login/entra", params=authorize_params())
    state = parse_qs(urlparse(go.headers["location"]).query)["state"][0]
    fake_provider(monkeypatch, {
        "aud": ENTRA["client_id"], "nonce": nonce_of(state), "oid": "guest-1",
        "preferred_username": "bob_gmail.com#EXT#@eunoia.onmicrosoft.com", "name": "Bob Guest"})
    back = client.get("/callback/entra", params={"code": "c", "state": state})
    assert exchange(code_from(back)[0])["email"] == "bob@gmail.com"


def test_a_refused_code_says_what_to_fix_on_the_entra_side(monkeypatch, tmp_path):
    """`invalid_client` with AADSTS700025 is the app being declared a public client."""
    configure(monkeypatch, tmp_path, {"entra": ENTRA})
    go = client.get("/login/entra", params=authorize_params())
    state = parse_qs(urlparse(go.headers["location"]).query)["state"][0]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={
            "error": "invalid_client",
            "error_description": "AADSTS700025: Client is public so neither 'client_assertion' "
            "nor 'client_secret' should be presented. Trace ID: abc secret=s3cret~value",
        })

    monkeypatch.setattr(providers, "http_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    failed = client.get("/callback/entra", params={"code": "c", "state": state})
    assert failed.status_code == 400
    assert "invalid_client, AADSTS700025" in failed.text
    assert "client public" in failed.text and "Plateforme" not in failed.text
    assert "plateforme « Web »" in failed.text
    # Never what Microsoft echoed back.
    assert "s3cret" not in failed.text and "Trace ID" not in failed.text
