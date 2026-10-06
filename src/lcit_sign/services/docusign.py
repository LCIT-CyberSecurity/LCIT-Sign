"""DocuSign eSignature REST API, the little of it LCIT Sign needs: sign in as an integration
(JWT grant: a signed assertion exchanged for a short-lived token), send one document to one
signer, follow its status, fetch the signed PDF and the certificate of completion.

The signer receives DocuSign's own e-mail and signs on DocuSign: LCIT Sign never handles the
signature itself. `environment` "demo" is DocuSign's developer sandbox, "production" the real
service; "test" points at the mock DocuSign of the test stack (addresses given in the settings).
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pypdf import PdfReader

from lcit_sign.models.document import FieldKind
from lcit_sign.services.field_stamping import PreparedField

AUTH_HOSTS = {"demo": "https://account-d.docusign.com", "production": "https://account.docusign.com"}
ENVIRONMENTS = ("demo", "production", "test")
SCOPES = "signature impersonation"


class DocusignError(Exception):
    """DocuSign refused, or could not be reached; the message is in the admin's words."""


@dataclass(frozen=True)
class DocusignSettings:
    environment: str
    integration_key: str
    user_id: str
    account_id: str
    private_key: str
    auth_url: str | None = None
    api_url: str | None = None

    @property
    def auth_base(self) -> str:
        if self.environment == "test":
            return (self.auth_url or "").rstrip("/")
        return AUTH_HOSTS[self.environment]


def _b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def load_private_key(pem: str) -> rsa.RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(pem.strip().encode(), password=None)
    except (ValueError, TypeError) as exc:
        raise DocusignError("La clé privée n'est pas une clé RSA au format PEM.") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise DocusignError("La clé privée n'est pas une clé RSA.")
    return key


def _describe(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = {}
    code = str(body.get("error") or body.get("errorCode") or "")
    detail = str(body.get("error_description") or body.get("message") or "")
    if code == "consent_required":
        return (
            "DocuSign attend le consentement d'un administrateur pour cette application : "
            "ouvrez le lien de consentement indiqué dans l'aide, puis réessayez."
        )
    if code == "invalid_grant":
        return (
            "DocuSign refuse la connexion (invalid_grant) : vérifiez la clé d'intégration, "
            "l'ID utilisateur et que la clé privée correspond à la clé publique de l'application."
        )
    text = f"{code} {detail}".strip() or f"réponse {response.status_code}"
    return f"DocuSign a refusé la demande ({text})."


class DocusignClient:
    def __init__(self, client: httpx.Client, settings: DocusignSettings) -> None:
        self._client = client
        self._settings = settings
        self._token: str | None = None
        self._base: str | None = None

    # -- connection --------------------------------------------------------------------

    def _assertion(self) -> str:
        key = load_private_key(self._settings.private_key)
        now = int(time.time())
        audience = self._settings.auth_base.split("://", 1)[-1]
        header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = _b64(
            json.dumps(
                {
                    "iss": self._settings.integration_key,
                    "sub": self._settings.user_id,
                    "aud": audience,
                    "iat": now,
                    "exp": now + 3600,
                    "scope": SCOPES,
                }
            ).encode()
        )
        signing_input = header + b"." + claims
        signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return (signing_input + b"." + _b64(signature)).decode()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise DocusignError("Impossible de joindre DocuSign.") from exc

    def token(self) -> str:
        if self._token is None:
            response = self._request(
                "POST",
                f"{self._settings.auth_base}/oauth/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": self._assertion(),
                },
            )
            if response.status_code != 200:
                raise DocusignError(_describe(response))
            self._token = str(response.json()["access_token"])
        return self._token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}

    def base(self) -> str:
        """`…/restapi/v2.1/accounts/{account}`: where DocuSign keeps this account."""
        if self._base is None:
            if self._settings.environment == "test" and self._settings.api_url:
                host = self._settings.api_url.rstrip("/")
            else:
                info = self._request(
                    "GET", f"{self._settings.auth_base}/oauth/userinfo", headers=self._headers()
                )
                if info.status_code != 200:
                    raise DocusignError(_describe(info))
                accounts = info.json().get("accounts", [])
                mine = next(
                    (a for a in accounts if a.get("account_id") == self._settings.account_id),
                    None,
                )
                if mine is None:
                    raise DocusignError(
                        "L'ID de compte ne figure pas parmi les comptes de cet utilisateur "
                        "DocuSign."
                    )
                host = str(mine["base_uri"]).rstrip("/")
            self._base = f"{host}/restapi/v2.1/accounts/{self._settings.account_id}"
        return self._base

    def check(self) -> str:
        """Sign in and find the account: returns what to show the admin."""
        self.base()
        return "Connexion à DocuSign réussie."

    # -- envelopes ---------------------------------------------------------------------

    def create_envelope(
        self,
        *,
        subject: str,
        message: str,
        document_name: str,
        pdf: bytes,
        signer_name: str,
        signer_email: str,
        fields: list[PreparedField],
    ) -> str:
        body = {
            "emailSubject": subject,
            "emailBlurb": message,
            "status": "sent",
            "documents": [
                {
                    "documentBase64": base64.b64encode(pdf).decode(),
                    "name": document_name,
                    "fileExtension": "pdf",
                    "documentId": "1",
                }
            ],
            "recipients": {
                "signers": [
                    {
                        "email": signer_email,
                        "name": signer_name,
                        "recipientId": "1",
                        "routingOrder": "1",
                        "tabs": tabs_for(fields, pdf),
                    }
                ]
            },
        }
        response = self._request(
            "POST", f"{self.base()}/envelopes", json=body, headers=self._headers()
        )
        if response.status_code not in (200, 201):
            raise DocusignError(_describe(response))
        return str(response.json()["envelopeId"])

    def status(self, envelope_id: str) -> str:
        """sent, delivered, completed, declined, voided…, in DocuSign's own words (lowercase)."""
        response = self._request(
            "GET", f"{self.base()}/envelopes/{envelope_id}", headers=self._headers()
        )
        if response.status_code != 200:
            raise DocusignError(_describe(response))
        return str(response.json().get("status", "")).lower()

    def _document(self, envelope_id: str, which: str) -> bytes:
        response = self._request(
            "GET",
            f"{self.base()}/envelopes/{envelope_id}/documents/{which}",
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise DocusignError(_describe(response))
        return response.content

    def signed_pdf(self, envelope_id: str) -> bytes:
        return self._document(envelope_id, "combined")

    def certificate(self, envelope_id: str) -> bytes:
        return self._document(envelope_id, "certificate")

    def void(self, envelope_id: str, reason: str) -> None:
        response = self._request(
            "PUT",
            f"{self.base()}/envelopes/{envelope_id}",
            json={"status": "voided", "voidedReason": reason},
            headers=self._headers(),
        )
        if response.status_code not in (200, 201):
            raise DocusignError(_describe(response))


# -- the elements LCIT Sign placed, as DocuSign "tabs" -------------------------------------

_TAB_KEYS = {
    FieldKind.SIGNATURE: "signHereTabs",
    FieldKind.DATE: "dateSignedTabs",
    FieldKind.FULL_NAME: "fullNameTabs",
    FieldKind.FIRST_NAME: "firstNameTabs",
    FieldKind.LAST_NAME: "lastNameTabs",
    FieldKind.EMAIL: "emailTabs",
    FieldKind.TEXT: "textTabs",
    FieldKind.PLACE: "textTabs",
}


def tabs_for(fields: list[PreparedField], pdf: bytes) -> dict[str, list[dict[str, Any]]]:
    """DocuSign places a tab by its top-left corner in points from the page's top-left; the
    elements are placed in fractions of the page, so the page size is read from the PDF.
    The company logo and the time have no DocuSign equivalent and are left out."""
    pages = PdfReader(BytesIO(pdf)).pages
    tabs: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        key = _TAB_KEYS.get(field.kind)
        if key is None or not 1 <= field.page <= len(pages):
            continue
        box = pages[field.page - 1].mediabox
        width, height = float(box.width), float(box.height)
        tab: dict[str, Any] = {
            "documentId": "1",
            "pageNumber": str(field.page),
            "xPosition": str(round(field.x * width)),
            "yPosition": str(round(field.y * height)),
        }
        if key == "textTabs":
            tab.update(
                tabLabel=field.label or f"champ-{field.id[:8]}",
                required=str(field.required).lower(),
                width=str(max(round(field.width * width), 20)),
                height=str(max(round(field.height * height), 12)),
            )
        tabs.setdefault(key, []).append(tab)
    return tabs
