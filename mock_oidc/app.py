"""Throwaway OpenID Connect provider for local development and CrashTests.

Not security hardened and must never be reachable from anything but a dev
or CI environment: it accepts any client_id/client_secret and lets the
browser pick which fictional identity to sign in as. Real SSO providers
(Entra ID, Google Workspace, Keycloak) are used for anything that matters.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime, timedelta

from authlib.jose import JsonWebKey, jwt
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

ISSUER = os.environ.get("MOCK_OIDC_ISSUER", "http://mock-oidc:8080")
PUBLIC_BASE_URL = os.environ.get("MOCK_OIDC_PUBLIC_BASE_URL", "http://localhost:8080")

# A small fictional organisation mirroring the CrashTest dataset groups
# (spec §115) — identity only; group membership belongs to the directory
# connectors built in a later phase.
TEST_USERS = {
    "u-direction-1": {
        "sub": "u-direction-1", "email": "alice.martin@lcit-test.local",
        "given_name": "Alice", "family_name": "Martin", "group": "Direction",
    },
    "u-rh-1": {
        "sub": "u-rh-1", "email": "bob.dupont@lcit-test.local",
        "given_name": "Bob", "family_name": "Dupont", "group": "RH",
    },
    "u-compta-1": {
        "sub": "u-compta-1", "email": "charlie.durand@lcit-test.local",
        "given_name": "Charlie", "family_name": "Durand", "group": "Comptabilite",
    },
    "u-sales-1": {
        "sub": "u-sales-1", "email": "diane.leroy@lcit-test.local",
        "given_name": "Diane", "family_name": "Leroy", "group": "Sales",
    },
    "u-it-1": {
        "sub": "u-it-1", "email": "erwan.petit@lcit-test.local",
        "given_name": "Erwan", "family_name": "Petit", "group": "IT",
    },
    "u-consultants-1": {
        "sub": "u-consultants-1", "email": "fatima.benali@lcit-test.local",
        "given_name": "Fatima", "family_name": "Benali", "group": "Consultants",
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

    params = (
        f"client_id={client_id}&redirect_uri={redirect_uri}&state={state}"
        f"&nonce={nonce}&code_challenge={code_challenge}"
    )
    options = "".join(
        f'<li><a href="authorize/choose?{params}&sub={sub}">'
        f"{user['given_name']} {user['family_name']} — {user['group']}</a></li>"
        for sub, user in TEST_USERS.items()
    )
    return HTMLResponse(f"""
        <html><body style="font-family: sans-serif; max-width: 480px; margin: 40px auto;">
          <h2>LCIT Sign — Mock SSO</h2>
          <p>Choisir une identité de test pour continuer :</p>
          <ul>{options}</ul>
        </body></html>
    """)


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

    return JSONResponse({
        "access_token": uuid.uuid4().hex,
        "token_type": "Bearer",
        "expires_in": 300,
        "id_token": id_token.decode("ascii") if isinstance(id_token, bytes) else id_token,
    })


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
