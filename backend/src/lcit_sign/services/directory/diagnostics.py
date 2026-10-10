"""Read-only connection tests for the directory connectors.

A test asks each provider for the least it can (one user, one group, one member), in the same
order a synchronisation would, and says in the administrator's words what works and what does
not: which step failed, the provider's own error code when it helps, and what to do about it.

Nothing here writes to the database, and nothing a provider answers is passed on as it came: only
a short, validated error code and our own wording. Secrets, tokens and response bodies never
reach a result, a log line or the audit."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OK, WARN, ERROR = "OK", "WARN", "ERROR"

# Our own codes (a small set: what the administrator can act on).
AUTH_FAILED = "AUTH_FAILED"
INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
SECRET_EXPIRED = "SECRET_EXPIRED"  # noqa: S105
TENANT_NOT_FOUND = "TENANT_NOT_FOUND"
INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
NETWORK_ERROR = "NETWORK_ERROR"
TIMEOUT = "TIMEOUT"
TLS_ERROR = "TLS_ERROR"
UPSTREAM_ERROR = "UPSTREAM_ERROR"
RATE_LIMITED = "RATE_LIMITED"
USER_READ_FAILED = "USER_READ_FAILED"
GROUP_READ_FAILED = "GROUP_READ_FAILED"
MEMBERSHIP_READ_FAILED = "MEMBERSHIP_READ_FAILED"
BASE_DN_ERROR = "BASE_DN_ERROR"
USER_QUERY_ERROR = "USER_QUERY_ERROR"
GROUP_QUERY_ERROR = "GROUP_QUERY_ERROR"

# Each request of a test gives up quickly: an administrator is waiting on the button.
TEST_TIMEOUT = 10.0

# A provider's error code is only ever shown if it looks like one (never free text).
_SAFE_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str
    code: str | None = None
    provider_code: str | None = None
    action: str | None = None

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def ok(name: str, message: str) -> CheckResult:
    return CheckResult(name, OK, message)


def warn(
    name: str, message: str, *, code: str | None = None, action: str | None = None
) -> CheckResult:
    return CheckResult(name, WARN, message, code=code, action=action)


def fail(
    name: str,
    code: str,
    message: str,
    *,
    provider_code: str | None = None,
    action: str | None = None,
) -> CheckResult:
    return CheckResult(name, ERROR, message, code=code, provider_code=provider_code, action=action)


def overall(checks: list[CheckResult]) -> str:
    if any(c.status == ERROR for c in checks):
        return ERROR
    if any(c.status == WARN for c in checks):
        return WARN
    return OK


def result_payload(source: str, checks: list[CheckResult]) -> dict[str, Any]:
    return {
        "source": source,
        "status": overall(checks),
        "checks": [c.payload() for c in checks],
    }


def safe_code(value: Any) -> str | None:
    """A provider's error code if it is short and made of code characters; nothing otherwise."""
    return value if isinstance(value, str) and _SAFE_CODE.match(value) else None


def log_check(source: str, check: CheckResult) -> None:
    """One line per step: which provider, which operation, how it went. No payloads."""
    level = logging.INFO if check.status == OK else logging.WARNING
    logger.log(
        level,
        "directory test source=%s operation=%s status=%s code=%s provider_code=%s",
        source,
        check.name,
        check.status,
        check.code,
        check.provider_code,
    )


# --- HTTP -----------------------------------------------------------------------------


def transport_failure(name: str, exc: Exception, *, service: str) -> CheckResult:
    """The request never got an answer: say whether it was the network, the clock or TLS."""
    text = f"{type(exc).__name__} {exc}".lower()
    if isinstance(exc, httpx.TimeoutException):
        return fail(
            name,
            TIMEOUT,
            f"{service} ne répond pas dans le délai imparti.",
            provider_code=type(exc).__name__,
            action="Vérifiez l'accès réseau du serveur LCIT Sign, puis réessayez.",
        )
    if "certificate" in text or "ssl" in text or "tls" in text:
        return fail(
            name,
            TLS_ERROR,
            f"La connexion sécurisée vers {service} a échoué (certificat non reconnu).",
            provider_code=type(exc).__name__,
            action="Vérifiez l'heure du serveur et les autorités de certification installées.",
        )
    return fail(
        name,
        NETWORK_ERROR,
        f"{service} est injoignable depuis le serveur LCIT Sign.",
        provider_code=type(exc).__name__,
        action="Vérifiez le pare-feu, le proxy et la résolution DNS du serveur.",
    )


def provider_error_code(response: httpx.Response) -> str | None:
    """The short code a provider puts in an error body (Graph `error.code`, Google
    `error.errors[0].reason` or `error.status`, OAuth `error`). Never the message."""
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, str):
        return safe_code(error)
    if isinstance(error, dict):
        reasons = error.get("errors")
        if isinstance(reasons, list) and reasons and isinstance(reasons[0], dict):
            found = safe_code(reasons[0].get("reason"))
            if found:
                return found
        return safe_code(error.get("code")) or safe_code(error.get("status"))
    return None


def http_provider_code(response: httpx.Response) -> str:
    detail = provider_error_code(response)
    return f"HTTP {response.status_code}" + (f" · {detail}" if detail else "")


def http_failure(
    name: str,
    response: httpx.Response,
    *,
    service: str,
    what: str,
    permission: str,
    read_failed: str,
) -> CheckResult:
    """A provider answered a read with an error status."""
    status = response.status_code
    provider = http_provider_code(response)
    if status == 401:
        return fail(
            name,
            AUTH_FAILED,
            f"{service} refuse le jeton d'accès.",
            provider_code=provider,
            action="Vérifiez les identifiants du connecteur, puis réessayez.",
        )
    if status == 403:
        return fail(
            name,
            INSUFFICIENT_PERMISSIONS,
            f"Lecture {what} refusée : permission {permission} absente.",
            provider_code=provider,
            action=f"Accordez la permission {permission} et le consentement administrateur.",
        )
    if status == 429:
        return fail(
            name,
            RATE_LIMITED,
            f"{service} limite le débit des requêtes.",
            provider_code=provider,
            action="Patientez quelques minutes avant de réessayer.",
        )
    if status >= 500:
        return fail(
            name,
            UPSTREAM_ERROR,
            f"{service} rencontre une panne (erreur {status}).",
            provider_code=provider,
            action="Il s'agit d'un incident côté fournisseur : réessayez plus tard.",
        )
    return fail(
        name,
        read_failed,
        f"Lecture {what} impossible ({service} a répondu {status}).",
        provider_code=provider,
        action="Vérifiez la configuration du connecteur.",
    )


def probe_get(
    client: httpx.Client,
    url: str,
    *,
    name: str,
    headers: dict[str, str],
    params: dict[str, str] | None = None,
    service: str,
    what: str,
    permission: str,
    read_failed: str,
    success: str,
) -> tuple[CheckResult, dict[str, Any] | None]:
    """One read-only GET. The parsed answer comes back only when it succeeded."""
    try:
        response = client.get(url, headers=headers, params=params, timeout=TEST_TIMEOUT)
    except httpx.HTTPError as exc:
        return transport_failure(name, exc, service=service), None
    if response.status_code != 200:
        return (
            http_failure(
                name, response, service=service, what=what, permission=permission,
                read_failed=read_failed,
            ),
            None,
        )
    try:
        body = response.json()
    except ValueError:
        return (
            fail(name, UPSTREAM_ERROR, f"{service} a répondu une réponse illisible.",
                 provider_code=f"HTTP {response.status_code}"),
            None,
        )
    return ok(name, success), body if isinstance(body, dict) else {}


# --- Explaining a failed synchronisation --------------------------------------------------

_SYNC_CODE = re.compile(
    r"(AADSTS\d+|unauthorized_client|invalid_grant|invalid_client|invalid_request"
    r"|HTTP \d{3}|'\d{3} [A-Za-z ]+')"
)

_SYNC_ACTIONS = {
    "AADSTS7000222": "Créer un nouveau secret dans Entra > Certificats et secrets.",
    "AADSTS7000215": "Recopier la colonne « Valeur » du secret (pas « ID du secret »).",
    "AADSTS700016": "Vérifier l'ID de l'application (client) et l'ID du tenant.",
    "AADSTS90002": "Vérifier l'ID du tenant.",
    "unauthorized_client": "Autoriser le compte de service pour la délégation à l'échelle "
    "du domaine (console Admin Google).",
    "invalid_grant": "Vérifier que l'administrateur imité existe et que la délégation est active.",
    "HTTP 403": "Vérifier les permissions du connecteur.",
    "HTTP 429": "Patienter quelques minutes avant de relancer.",
}


def explain_sync_error(text: str | None) -> dict[str, str | None] | None:
    """A synchronisation that failed stores one sentence. Pull out the provider's code and the
    matching advice when the sentence has them; otherwise the sentence stands alone."""
    if not text:
        return None
    found = _SYNC_CODE.search(text)
    code = found.group(1) if found else None
    if code and code.startswith("'"):
        code = "HTTP " + code.strip("'").split()[0]
    return {"message": text, "provider_code": code, "action": _SYNC_ACTIONS.get(code or "")}
