"""Google Workspace: send through the Gmail API, as one mailbox, with a service account
authorised by domain-wide delegation (scope gmail.send only)."""
from __future__ import annotations

import base64
import json
from email.message import EmailMessage

import httpx

from lcit_sign.services.connector_fields import FieldSpec
from lcit_sign.services.google_auth import GoogleAuthError, ServiceAccount
from lcit_sign.services.mail import MailSendError
from lcit_sign.services.mail_spec import MailSpec

SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SCOPE = "https://www.googleapis.com/auth/gmail.send"


class GmailSender:
    kind = "gmail"

    def __init__(
        self,
        client: httpx.Client,
        *,
        service_account_json: str,
        mailbox: str,
        reply_to: str | None = None,
    ) -> None:
        self._client = client
        self._mailbox = mailbox
        self._reply_to = reply_to
        try:
            self._account = ServiceAccount(service_account_json)
        except GoogleAuthError as exc:
            raise MailSendError(str(exc), permanent=True) from exc

    def _token(self) -> str:
        try:
            return self._account.token(self._client, SCOPE, self._mailbox)
        except GoogleAuthError as exc:
            raise MailSendError(str(exc)) from exc

    def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._mailbox
        message["To"] = to
        message["Subject"] = subject
        if self._reply_to:
            message["Reply-To"] = self._reply_to
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        try:
            response = self._client.post(
                SEND_URL,
                headers={"Authorization": f"Bearer {self._token()}"},
                content=json.dumps({"raw": raw}),
            )
        except httpx.HTTPError as exc:
            raise MailSendError(f"Could not reach Gmail: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise MailSendError(
                f"Gmail refused the message (HTTP {response.status_code})",
                # A request Google rejects as invalid will not get better by retrying;
                # server-side and rate-limit answers might.
                permanent=response.status_code in (400, 403, 404),
            )

    def diagnose(self) -> dict[str, str]:
        results = {"token": "SKIPPED"}
        try:
            self._token()
            results["token"] = "OK"  # noqa: S105
        except MailSendError as exc:
            results["token"] = f"FAIL: {exc}"
        return results


def validate(fields: dict[str, str], secret: str | None) -> None:
    if "@" not in fields.get("from_address", ""):
        raise ValueError(
            "La boîte d'envoi doit être une adresse Google Workspace (signature@votre-domaine.fr)."
        )
    if secret is not None:
        try:
            key = json.loads(secret)
            valid = isinstance(key, dict) and "client_email" in key and "private_key" in key
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "La clé du compte de service doit être le fichier JSON téléchargé depuis Google "
                "Cloud (« client_email » et « private_key »)."
            )


SPEC = MailSpec(
    kind="gmail",
    label="Google Workspace (Gmail)",
    description=(
        "Envoie depuis une boîte de votre domaine Google Workspace avec un compte de service "
        "autorisé par délégation à l'échelle du domaine, pour la seule portée « gmail.send » "
        "(console Admin → Sécurité → Contrôle des accès et des données → Contrôles des API)."
    ),
    fields=(
        FieldSpec(
            "from_address",
            "Boîte d'envoi",
            "La boîte Gmail au nom de laquelle les e-mails partent : le compte de service agit "
            "pour elle. Elle doit exister dans votre domaine Google Workspace.",
            "signature@votre-domaine.fr",
        ),
        FieldSpec(
            "reply_to",
            "Répondre à",
            "Facultatif : l'adresse qui reçoit les réponses.",
            "support@votre-domaine.fr",
            required=False,
        ),
    ),
    secret=FieldSpec(
        "password",
        "Clé du compte de service (JSON)",
        "Le contenu du fichier JSON téléchargé depuis Google Cloud (IAM → Comptes de service → "
        "Clés → Créer une clé). Chiffré ici, jamais réaffiché.",
        '{"type": "service_account", "client_email": "…", "private_key": "…"}',
        kind="textarea",
    ),
    validate=validate,
)
