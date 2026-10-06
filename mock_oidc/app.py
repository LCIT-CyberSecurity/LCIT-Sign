"""Throwaway OpenID Connect provider for local development and CrashTests.

Not security hardened and must never be reachable from anything but a dev
or CI environment: it accepts any client_id/client_secret and lets the
browser pick which fictional identity to sign in as. Real SSO providers
(Entra ID, Google Workspace, Keycloak) are used for anything that matters.
"""

from __future__ import annotations

import html
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import real_providers as providers
from authlib.jose import JsonWebKey, jwt
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

ISSUER = os.environ.get("MOCK_OIDC_ISSUER", "http://mock-oidc:8080")
PUBLIC_BASE_URL = os.environ.get("MOCK_OIDC_PUBLIC_BASE_URL", "http://localhost:8080")

# A small fictional organisation mirroring the CrashTest dataset groups
# (spec §115) — identity only; group membership belongs to the directory
# connectors built in a later phase.
TEST_USERS = {
    "u-direction-1": {
        "sub": "u-direction-1",
        "email": "alice.martin@lcit-test.local",
        "given_name": "Alice",
        "family_name": "Martin",
        "group": "Direction",
    },
    "u-rh-1": {
        "sub": "u-rh-1",
        "email": "bob.dupont@lcit-test.local",
        "given_name": "Bob",
        "family_name": "Dupont",
        "group": "RH",
    },
    "u-compta-1": {
        "sub": "u-compta-1",
        "email": "charlie.durand@lcit-test.local",
        "given_name": "Charlie",
        "family_name": "Durand",
        "group": "Comptabilite",
    },
    "u-sales-1": {
        "sub": "u-sales-1",
        "email": "diane.leroy@lcit-test.local",
        "given_name": "Diane",
        "family_name": "Leroy",
        "group": "Sales",
    },
    "u-it-1": {
        "sub": "u-it-1",
        "email": "erwan.petit@lcit-test.local",
        "given_name": "Erwan",
        "family_name": "Petit",
        "group": "IT",
    },
    "u-consultants-1": {
        "sub": "u-consultants-1",
        "email": "fatima.benali@lcit-test.local",
        "given_name": "Fatima",
        "family_name": "Benali",
        "group": "Consultants",
    },
}

_KEY_ID = "mock-oidc-dev-key"
_private_key = JsonWebKey.generate_key("RSA", 2048, options={"kid": _KEY_ID}, is_private=True)
_public_jwk = _private_key.as_dict(is_private=False)

_pending_codes: dict[str, dict] = {}
_CODE_TTL_SECONDS = 120

app = FastAPI(title="LCIT Sign — Mock OIDC Provider")


@app.get("/.well-known/openid-configuration")
def discovery() -> dict:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{PUBLIC_BASE_URL}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks.json",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }


@app.get("/jwks.json")
def jwks() -> dict:
    return {"keys": [_public_jwk]}


def _require_allowed(redirect_uri: str, *, real: bool = False) -> None:
    """Codes only go where the app says they may (MOCK_OIDC_ALLOWED_REDIRECTS). Real accounts
    are refused outright without that list: a crafted link could otherwise hand someone else the
    code of a person who just signed in."""
    if not providers.redirect_allowed(redirect_uri):
        raise HTTPException(400, "redirect_uri not allowed")
    if real and not providers.real_login_possible():
        raise HTTPException(
            400, "Real accounts need MOCK_OIDC_ALLOWED_REDIRECTS to be set on this server"
        )


def _page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"""<html><head><meta charset="utf-8"><title>LCIT Sign — Mock SSO</title></head>
        <body style="font-family: sans-serif; max-width: 520px; margin: 40px auto;">
        <h2>LCIT Sign — Mock SSO</h2>{body}</body></html>""",
        status_code=status,
    )


def _chooser(params: dict[str, str], error: str | None = None, status: int = 200) -> HTMLResponse:
    """Test identities, and — when the server has them — real Entra / Google / LDAP accounts."""
    query = urlencode(params)
    users = "".join(
        f'<li><a href="authorize/choose?{html.escape(query)}&amp;sub={html.escape(sub)}">'
        f"{html.escape(user['given_name'])} {html.escape(user['family_name'])} — "
        f"{html.escape(user['group'])}</a></li>"
        for sub, user in TEST_USERS.items()
    )
    configured = providers.load_config() if providers.real_login_possible() else {}
    real = ""
    for name in ("entra", "google"):
        label = html.escape(providers.LABELS[name])
        real += (
            f'<li><a href="login/{name}?{html.escape(query)}">Se connecter avec {label}</a></li>'
            if name in configured
            else f'<li style="color:#888">{label} — non configuré sur ce serveur</li>'
        )
    if "ldap" in configured:
        hidden = "".join(
            f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
            for k, v in params.items()
        )
        real += f"""<li>{html.escape(providers.LABELS["ldap"])} :
          <form method="post" action="login/ldap" autocomplete="off" style="margin:6px 0">
            {hidden}
            <input name="login" placeholder="identifiant ou e-mail" required>
            <input name="password" type="password" placeholder="mot de passe" required
                   autocomplete="off">
            <button type="submit">Se connecter</button>
          </form></li>"""
    else:
        label = html.escape(providers.LABELS["ldap"])
        real += f'<li style="color:#888">{label} — non configuré sur ce serveur</li>'
    alert = f'<p style="color:#b42318" role="alert">{html.escape(error)}</p>' if error else ""
    return _page(
        f"""{alert}<p>Choisir une identité de test pour continuer :</p><ul>{users}</ul>
        <p>Ou un compte réel (le mot de passe n'est jamais vu par LCIT Sign) :</p>
        <ul>{real}</ul>""",
        status,
    )


@app.get("/authorize", response_class=HTMLResponse)
def authorize(
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    state: str = Query(...),
    nonce: str = Query(...),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query("S256"),
    response_type: str = Query("code"),
) -> HTMLResponse:
    if response_type != "code" or code_challenge_method != "S256":
        raise HTTPException(400, "Unsupported request")
    _require_allowed(redirect_uri)
    return _chooser(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
        }
    )


def _issue_code(
    user: dict[str, str],
    client_id: str,
    redirect_uri: str,
    nonce: str,
    code_challenge: str,
    state: str,
) -> RedirectResponse:
    code = uuid.uuid4().hex
    _pending_codes[code] = {
        "user": user,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "issued_at": time.time(),
    }
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{separator}code={code}&state={state}")


@app.get("/authorize/choose")
def authorize_choose(
    sub: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    state: str = Query(...),
    nonce: str = Query(...),
    code_challenge: str = Query(...),
) -> RedirectResponse:
    user = TEST_USERS.get(sub)
    if user is None:
        raise HTTPException(404, "Unknown test identity")
    _require_allowed(redirect_uri)
    return _issue_code(user, client_id, redirect_uri, nonce, code_challenge, state)


@app.get("/login/{provider}")
def login_with(
    provider: str,
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    state: str = Query(...),
    nonce: str = Query(...),
    code_challenge: str = Query(...),
) -> RedirectResponse:
    """Entra or Google: on to the provider's own login page."""
    _require_allowed(redirect_uri, real=True)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
    }
    try:
        return RedirectResponse(providers.begin(provider, params, PUBLIC_BASE_URL))
    except LookupError:
        raise HTTPException(404, "Fournisseur inconnu ou non configuré") from None


@app.get("/callback/{provider}")
def provider_callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    """The provider sends the person back: who are they, then on to the app with our own code."""
    if error or not code or not state:
        return _page("<p>La connexion a été annulée ou refusée par le fournisseur.</p>", 400)
    try:
        user, params = providers.finish(provider, code, state, PUBLIC_BASE_URL)
    except providers.ProviderError as exc:
        return _page(f'<p role="alert">{html.escape(str(exc))}</p>', 400)
    _require_allowed(params["redirect_uri"], real=True)
    return _issue_code(
        user,
        params["client_id"],
        params["redirect_uri"],
        params["nonce"],
        params["code_challenge"],
        params["state"],
    )


@app.post("/login/ldap")
def login_ldap(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(...),
    nonce: str = Form(...),
    code_challenge: str = Form(...),
) -> Response:
    """LDAP: the password is asked here (never by LCIT Sign), checked against the directory,
    and dropped."""
    _require_allowed(redirect_uri, real=True)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
    }
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "?")
    try:
        user = providers.ldap_login(login, password, ip)
    except providers.ProviderError as exc:
        return _chooser(params, str(exc), 429)
    if user is None:
        # The same answer whether the login is unknown or the password wrong.
        return _chooser(params, "Identifiant ou mot de passe incorrect.", 401)
    return _issue_code(user, client_id, redirect_uri, nonce, code_challenge, state)


@app.post("/token")
def token(
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    code_verifier: str = Form(...),
) -> JSONResponse:
    if grant_type != "authorization_code":
        raise HTTPException(400, "Unsupported grant_type")

    pending = _pending_codes.pop(code, None)
    if pending is None or time.time() - pending["issued_at"] > _CODE_TTL_SECONDS:
        raise HTTPException(400, "Invalid or expired code")
    if pending["redirect_uri"] != redirect_uri or pending["client_id"] != client_id:
        raise HTTPException(400, "redirect_uri or client_id mismatch")

    if create_s256_code_challenge(code_verifier) != pending["code_challenge"]:
        raise HTTPException(400, "Invalid code_verifier")

    user = pending["user"]
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "sub": user["sub"],
        "aud": client_id,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "nonce": pending["nonce"],
        "email": user["email"],
        "given_name": user["given_name"],
        "family_name": user["family_name"],
        "name": f"{user['given_name']} {user['family_name']}",
    }
    id_token = jwt.encode({"alg": "RS256", "kid": _KEY_ID}, claims, _private_key)

    return JSONResponse(
        {
            "access_token": uuid.uuid4().hex,
            "token_type": "Bearer",
            "expires_in": 300,
            "id_token": id_token.decode("ascii") if isinstance(id_token, bytes) else id_token,
        }
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
