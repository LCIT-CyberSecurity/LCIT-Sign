from __future__ import annotations

import hashlib
import time
from urllib.parse import quote

import httpx

from lcit_sign.services.aad_errors import describe_token_error
from lcit_sign.services.mail import MailSendError

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"

# Access tokens live only in this process's memory (spec §64): never
# stored, renewed on demand a minute before they expire. The key includes
# a digest of the client secret so replacing the secret in the admin UI
# can never keep serving a token minted with the old one.
_token_cache: dict[tuple[str, str, str], tuple[str, float]] = {}


def _error_code(response: httpx.Response) -> str:
    """The Graph/AAD error *code* only — never the body, which may echo
    request details."""
    try:
        data = response.json()
    except ValueError:
        return "unknown"
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("code", "unknown"))
    return str(error or data.get("error_description", "unknown"))[:80]


class GraphSender:
    """Send mail through Microsoft Graph with an app-only token, from one
    dedicated mailbox. The tenant must restrict the application to that
    mailbox with Exchange Online Application RBAC (spec §62); `test_isolation`
    proves it does.
    """

    kind = "graph"

    def __init__(
        self,
        client: httpx.Client,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        mailbox: str,
        reply_to: str | None = None,
    ) -> None:
        self._client = client
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._mailbox = mailbox
        self._reply_to = reply_to

    def _token(self) -> str:
        digest = hashlib.sha256(self._client_secret.encode()).hexdigest()
        key = (self._tenant_id, self._client_id, digest)
        cached = _token_cache.get(key)
        if cached and cached[1] > time.monotonic() + 60:
            return cached[0]
        try:
            response = self._client.post(
                f"{LOGIN}/{quote(self._tenant_id, safe='')}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
            )
        except httpx.HTTPError as exc:
            raise MailSendError(f"Could not reach Microsoft login: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise MailSendError(describe_token_error(response))
        data = response.json()
        _token_cache[key] = (data["access_token"], time.monotonic() + int(data["expires_in"]))
        return str(data["access_token"])

    def _send_as(self, mailbox: str, *, to: str, subject: str, body: str) -> httpx.Response:
        message: dict[str, object] = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }
        if self._reply_to:
            message["replyTo"] = [{"emailAddress": {"address": self._reply_to}}]
        try:
            return self._client.post(
                f"{GRAPH}/users/{quote(mailbox, safe='@')}/sendMail",
                headers={"Authorization": f"Bearer {self._token()}"},
                json={"message": message, "saveToSentItems": False},
            )
        except httpx.HTTPError as exc:
            raise MailSendError(f"Could not reach Microsoft Graph: {type(exc).__name__}") from exc

    def send(self, *, to: str, subject: str, body: str) -> None:
        response = self._send_as(self._mailbox, to=to, subject=subject, body=body)
        if response.status_code != 202:
            raise MailSendError(
                f"Microsoft Graph refused the message (HTTP {response.status_code}, "
                f"{_error_code(response)})"
            )

    def diagnose(self) -> dict[str, str]:
        results = {"token": "SKIPPED"}
        try:
            self._token()
            results["token"] = "OK"  # noqa: S105
        except MailSendError as exc:
            results["token"] = f"FAIL: {exc}"
        return results

    def test_isolation(self, other_mailbox: str, to: str) -> bool:
        """Spec §63 step 9, the mandatory negative test: try to send AS a
        mailbox that is *not* the dedicated one. Returns True when Exchange
        refuses (the application is properly confined). If the message is
        accepted, the tenant grants unbounded Mail.Send — it was sent, to
        `to` only, and the caller must report the misconfiguration."""
        if other_mailbox.strip().lower() == self._mailbox.strip().lower():
            raise MailSendError("the probe mailbox must differ from the dedicated mailbox")
        response = self._send_as(
            other_mailbox,
            to=to,
            subject="LCIT Sign — test d'isolation (ne pas tenir compte)",
            body="Si vous lisez ce message, LCIT Sign peut envoyer depuis cette boîte : "
            "l'accès Mail.Send n'est pas limité. Corrigez la configuration Exchange RBAC.",
        )
        return response.status_code in (401, 403, 404)
