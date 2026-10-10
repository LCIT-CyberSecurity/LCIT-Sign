"""Read-only check of a sign-in provider (Administration > Connexion): is the provider reachable,
and does it accept the saved application identifiers and secret? Nothing is signed in, no user is
looked at, and nothing is stored. Only our own wording and a short provider code are returned."""
from __future__ import annotations

import httpx

from lcit_sign.services import aad_errors
from lcit_sign.services.directory import diagnostics as diag

ENTRA_AUTHORITY = "https://login.microsoftonline.com"
GOOGLE_DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105


def _discovery(client: httpx.Client, url: str, *, service: str, tenant: bool) -> diag.CheckResult:
    try:
        response = client.get(url, timeout=diag.TEST_TIMEOUT)
    except httpx.HTTPError as exc:
        return diag.transport_failure("discovery", exc, service=service)
    if response.status_code == 200:
        return diag.ok("discovery", f"{service} est joignable et connaît cette configuration.")
    if tenant and response.status_code in (400, 404):
        return diag.fail(
            "discovery",
            diag.TENANT_NOT_FOUND,
            "Le tenant est introuvable.",
            provider_code=diag.http_provider_code(response),
            action="Vérifiez l'ID du tenant (Entra > Vue d'ensemble).",
        )
    return diag.http_failure(
        "discovery", response, service=service, what="de la configuration", permission="",
        read_failed=diag.UPSTREAM_ERROR,
    )


def test_entra(
    client: httpx.Client, tenant: str, client_id: str, secret: str
) -> list[diag.CheckResult]:
    checks = [
        _discovery(
            client, f"{ENTRA_AUTHORITY}/{tenant}/v2.0/.well-known/openid-configuration",
            service="Microsoft", tenant=True,
        )
    ]
    if checks[0].status != diag.OK:
        return checks
    try:
        response = client.post(
            f"{ENTRA_AUTHORITY}/{tenant}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": secret,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=diag.TEST_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        checks.append(diag.transport_failure("credentials", exc, service="Microsoft"))
        return checks
    if response.status_code == 200:
        checks.append(diag.ok("credentials", "L'ID de l'application et le secret sont acceptés."))
    else:
        failure = aad_errors.classify_token_error(response)
        checks.append(
            diag.CheckResult(
                "credentials", failure.status, failure.message, failure.code,
                failure.provider_code, failure.action,
            )
        )
    return checks


def test_google(
    client: httpx.Client, client_id: str, secret: str, redirect_uri: str
) -> list[diag.CheckResult]:
    checks = [_discovery(client, GOOGLE_DISCOVERY, service="Google", tenant=False)]
    if checks[0].status != diag.OK:
        return checks
    # A deliberately invalid authorisation code: Google first checks the client. "invalid_client"
    # means the ID or the secret is wrong; "invalid_grant" means the client was accepted and only
    # the (fake) code was refused.
    try:
        response = client.post(
            GOOGLE_TOKEN_URI,
            data={
                "grant_type": "authorization_code",
                "code": "lcit-sign-connection-test",
                "client_id": client_id,
                "client_secret": secret,
                "redirect_uri": redirect_uri,
            },
            timeout=diag.TEST_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        checks.append(diag.transport_failure("credentials", exc, service="Google"))
        return checks
    code = diag.provider_error_code(response)
    if code in ("invalid_grant", "redirect_uri_mismatch"):
        checks.append(diag.ok("credentials", "L'ID client et le secret sont acceptés."))
    elif code == "invalid_client":
        checks.append(
            diag.fail(
                "credentials", diag.INVALID_CREDENTIALS,
                "Google refuse l'ID client ou le secret.",
                provider_code=code,
                action="Dans Google Cloud > Identifiants, copiez l'ID client et le secret "
                "du client OAuth, sans espace avant ou après.",
            )
        )
    else:
        checks.append(
            diag.fail(
                "credentials", diag.AUTH_FAILED, "Google a refusé la vérification du client.",
                provider_code=code or f"HTTP {response.status_code}",
                action="Vérifiez l'ID client et le secret du client OAuth.",
            )
        )
    return checks
