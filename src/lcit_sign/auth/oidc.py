from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from authlib.common.security import generate_token
from authlib.jose import JsonWebKey
from authlib.jose import jwt as jose_jwt
from authlib.jose.errors import JoseError
from authlib.oauth2.rfc7636 import create_s256_code_challenge


class OidcError(Exception):
    """Raised on any discovery, exchange or ID-token validation failure.

    Deliberately generic to the caller: the HTTP layer turns every instance
    into the same 400 response, never echoing provider internals back to
    the browser.
    """


@dataclass(frozen=True)
class ProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


@dataclass(frozen=True)
class AuthorizationRequest:
    url: str
    state: str
    nonce: str
    code_verifier: str


@dataclass(frozen=True)
class IdentityClaims:
    subject: str
    issuer: str
    email: str
    given_name: str
    family_name: str
    name: str


_metadata_cache: dict[str, tuple[float, ProviderMetadata]] = {}
_METADATA_TTL_SECONDS = 3600


async def discover_provider(issuer: str) -> ProviderMetadata:
    cached = _metadata_cache.get(issuer)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url)
    if response.status_code != 200:
        raise OidcError(f"OIDC discovery failed for issuer {issuer!r}")
    data = response.json()
    try:
        metadata = ProviderMetadata(
            issuer=data["issuer"],
            authorization_endpoint=data["authorization_endpoint"],
            token_endpoint=data["token_endpoint"],
            jwks_uri=data["jwks_uri"],
        )
    except KeyError as exc:
        raise OidcError("OIDC discovery document is missing a required field") from exc

    _metadata_cache[issuer] = (time.monotonic() + _METADATA_TTL_SECONDS, metadata)
    return metadata


def build_authorization_request(
    metadata: ProviderMetadata, *, client_id: str, redirect_uri: str
) -> AuthorizationRequest:
    state = generate_token(32)
    nonce = generate_token(32)
    code_verifier = generate_token(64)
    code_challenge = create_s256_code_challenge(code_verifier)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    url = metadata.authorization_endpoint + "?" + urlencode(params)
    return AuthorizationRequest(url=url, state=state, nonce=nonce, code_verifier=code_verifier)


async def exchange_code(
    metadata: ProviderMetadata,
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
    code_verifier: str,
    expected_nonce: str,
) -> IdentityClaims:
    async with httpx.AsyncClient(timeout=10) as client:
        token_response = await client.post(
            metadata.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )
        if token_response.status_code != 200:
            raise OidcError("Token exchange failed")
        token_data = token_response.json()
        id_token = token_data.get("id_token")
        if not id_token:
            raise OidcError("Token response is missing id_token")

        jwks_response = await client.get(metadata.jwks_uri)
        if jwks_response.status_code != 200:
            raise OidcError("Failed to fetch provider JWKS")
        key_set = JsonWebKey.import_key_set(jwks_response.json())

    try:
        claims = jose_jwt.decode(
            id_token,
            key_set,
            claims_options={
                "iss": {"values": [metadata.issuer]},
                "aud": {"values": [client_id]},
            },
        )
        claims.validate()
    except JoseError as exc:
        raise OidcError(f"Invalid ID token: {exc}") from exc

    if claims.get("nonce") != expected_nonce:
        raise OidcError("ID token nonce does not match the login attempt")

    subject = claims.get("sub")
    if not subject:
        raise OidcError("ID token is missing a subject")

    return IdentityClaims(
        subject=subject,
        issuer=str(claims.get("iss", metadata.issuer)),
        email=claims.get("email", ""),
        given_name=claims.get("given_name", ""),
        family_name=claims.get("family_name", ""),
        name=claims.get("name", ""),
    )
