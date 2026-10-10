"""Google service-account access (domain-wide delegation): a signed assertion exchanged for
a short-lived access token, for the scopes asked and the person impersonated. Used by the
directory connector (read the users) and the mail connector (send as a mailbox)."""
from __future__ import annotations

import base64
import json
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from lcit_sign.services.directory import diagnostics as diag

TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105


class GoogleAuthError(Exception):
    """The service account is unusable, or Google refused the token."""


def _b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


class ServiceAccount:
    def __init__(self, service_account_json: str) -> None:
        try:
            info = json.loads(service_account_json)
            self.client_email: str = info["client_email"]
            key = serialization.load_pem_private_key(info["private_key"].encode(), password=None)
            if not isinstance(key, rsa.RSAPrivateKey):
                raise ValueError("private_key is not an RSA key")
            self._private_key = key
        except (ValueError, KeyError, TypeError) as exc:
            raise GoogleAuthError(f"invalid Google service account: {exc}") from exc

    def assertion(self, scopes: str, subject: str) -> str:
        now = int(time.time())
        header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = _b64(
            json.dumps(
                {
                    "iss": self.client_email,
                    "sub": subject,
                    "scope": scopes,
                    "aud": TOKEN_URI,
                    "iat": now,
                    "exp": now + 3600,
                }
            ).encode()
        )
        signing_input = header + b"." + claims
        signature = self._private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return (signing_input + b"." + _b64(signature)).decode()

    def token(self, client: httpx.Client, scopes: str, subject: str) -> str:
        try:
            response = client.post(
                TOKEN_URI,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": self.assertion(scopes, subject),
                },
            )
        except httpx.HTTPError as exc:
            raise GoogleAuthError(
                f"Impossible de joindre Google ({type(exc).__name__}) : vérifiez l'accès réseau."
            ) from exc
        if response.status_code != 200:
            raise GoogleAuthError(describe_google_token_error(response, scopes, subject))
        try:
            return str(response.json()["access_token"])
        except (ValueError, KeyError) as exc:
            raise GoogleAuthError("Réponse inattendue de Google") from exc


def describe_google_token_error(response: httpx.Response, scopes: str, subject: str) -> str:
    """What to fix, in the admin's words. Never echoes the response body."""
    try:
        code = str(response.json().get("error", ""))
    except ValueError:
        code = ""
    short = scopes.replace("https://www.googleapis.com/auth/", "").replace(" ", ", ")
    if code == "unauthorized_client":
        return (
            f"Google refuse la délégation ({code}) : dans la console Admin (Sécurité → Contrôle "
            "des accès et des données → Contrôles des API → Délégation à l'échelle du domaine), "
            "autorisez "
            f"l'ID client du compte de service pour les portées : {short}."
        )
    if code == "invalid_grant":
        return (
            f"Google refuse d'agir au nom de {subject} ({code}) : cette adresse n'existe pas dans "
            "le domaine, ou la délégation à l'échelle du domaine n'est pas encore active (jusqu'à "
            "quelques minutes après l'autorisation)."
        )
    if code in ("invalid_client", "invalid_request"):
        return (
            f"La clé du compte de service n'est pas valide ({code}) : "
            "générez-en une nouvelle (format JSON)."
        )
    return f"Google a refusé l'authentification (HTTP {response.status_code}, {code or 'inconnu'})."


def classify_google_token_error(response: httpx.Response, subject: str) -> diag.CheckResult:
    """The connection test's view of a refused token request. Never echoes the body."""
    code = diag.provider_error_code(response) or ""
    provider = code or f"HTTP {response.status_code}"
    if code == "unauthorized_client":
        return diag.fail(
            "delegation",
            diag.INSUFFICIENT_PERMISSIONS,
            "Le compte de service n'est pas autorisé pour la délégation à l'échelle du domaine.",
            provider_code=provider,
            action="Console Admin > Sécurité > Contrôles des API > Délégation à l'échelle du "
            "domaine : autorisez l'ID client du compte de service avec les trois portées en "
            "lecture seule.",
        )
    if code == "invalid_grant":
        return diag.fail(
            "delegation",
            diag.INVALID_CONFIGURATION,
            f"Google refuse d'agir au nom de {subject} : adresse inexistante dans le domaine, "
            "ou délégation pas encore active.",
            provider_code=provider,
            action="Vérifiez l'e-mail de l'administrateur ; la délégation peut demander "
            "quelques minutes pour s'activer.",
        )
    if code in ("invalid_client", "invalid_request"):
        return diag.fail(
            "token_exchange",
            diag.INVALID_CONFIGURATION,
            "La clé du compte de service est refusée par Google.",
            provider_code=provider,
            action="Générez une nouvelle clé JSON pour le compte de service.",
        )
    return diag.fail(
        "token_exchange",
        diag.AUTH_FAILED,
        "Google a refusé l'authentification du compte de service.",
        provider_code=provider,
        action="Vérifiez la clé du compte de service et l'e-mail de l'administrateur.",
    )
