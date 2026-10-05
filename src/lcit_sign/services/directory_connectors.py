from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from lcit_sign.models.directory import DirectoryConnectorConfig
from lcit_sign.services.crypto import decrypt_secret


class DirectoryConnectorError(Exception):
    """The upstream directory was unreachable, refused us, or answered
    something we can't use. Surfaced on the sync run, never swallowed."""


@dataclass
class DirUser:
    external_id: str
    email: str
    given_name: str
    family_name: str
    active: bool = True
    group_ids: set[str] = field(default_factory=set)


@dataclass
class DirGroup:
    external_id: str
    name: str
    description: str = ""


@dataclass
class DirectorySnapshot:
    users: list[DirUser]
    groups: list[DirGroup]


class DirectoryConnector(Protocol):
    source: str

    def fetch(self) -> DirectorySnapshot: ...


def _split_name(display_name: str) -> tuple[str, str]:
    given, _, family = display_name.partition(" ")
    return given, family


def _get_json(client: httpx.Client, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = client.get(url, **kwargs)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DirectoryConnectorError(f"GET {url.split('?')[0]} failed: {exc}") from exc
    return data


def _post_token(client: httpx.Client, url: str, data: dict[str, str]) -> str:
    try:
        response = client.post(url, data=data)
        response.raise_for_status()
        token = response.json()["access_token"]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise DirectoryConnectorError(f"token request failed: {exc}") from exc
    return str(token)


class EntraConnector:
    """Microsoft Entra ID via Microsoft Graph, app-only (client
    credentials). Needs User.Read.All, Group.Read.All and
    GroupMember.Read.All application permissions, read-only (spec §22-30).
    """

    source = "entra"
    GRAPH = "https://graph.microsoft.com/v1.0"

    def __init__(
        self, client: httpx.Client, *, tenant_id: str, client_id: str, client_secret: str
    ) -> None:
        self._client = client
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret

    def _pages(self, url: str, headers: dict[str, str]) -> Iterator[dict[str, Any]]:
        next_url: str | None = url
        while next_url:
            page = _get_json(self._client, next_url, headers=headers)
            yield from page.get("value", [])
            next_url = page.get("@odata.nextLink")

    def fetch(self) -> DirectorySnapshot:
        token = _post_token(
            self._client,
            f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token",
            {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        headers = {"Authorization": f"Bearer {token}"}

        users: dict[str, DirUser] = {}
        select = "id,mail,userPrincipalName,givenName,surname,displayName,accountEnabled"
        for raw in self._pages(f"{self.GRAPH}/users?$select={select}&$top=999", headers):
            email = raw.get("mail") or raw.get("userPrincipalName")
            if not email:
                continue
            given = raw.get("givenName") or ""
            family = raw.get("surname") or ""
            if not given and not family:
                given, family = _split_name(raw.get("displayName") or email)
            users[raw["id"]] = DirUser(
                external_id=raw["id"],
                email=email.lower(),
                given_name=given,
                family_name=family,
                active=bool(raw.get("accountEnabled", True)),
            )

        groups: list[DirGroup] = []
        for raw in self._pages(
            f"{self.GRAPH}/groups?$select=id,displayName,description&$top=999", headers
        ):
            name = raw.get("displayName") or raw["id"]
            groups.append(DirGroup(raw["id"], name, raw.get("description") or ""))
            members_url = f"{self.GRAPH}/groups/{raw['id']}/members?$select=id&$top=999"
            for member in self._pages(members_url, headers):
                if member.get("@odata.type") == "#microsoft.graph.user" and member["id"] in users:
                    users[member["id"]].group_ids.add(raw["id"])
        return DirectorySnapshot(users=list(users.values()), groups=groups)


class GoogleWorkspaceConnector:
    """Google Workspace via the Admin SDK Directory API, using a service
    account with domain-wide delegation impersonating `admin_email`.
    Read-only scopes only.
    """

    source = "google"
    TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105
    API = "https://admin.googleapis.com/admin/directory/v1"
    SCOPES = " ".join(
        [
            "https://www.googleapis.com/auth/admin.directory.user.readonly",
            "https://www.googleapis.com/auth/admin.directory.group.readonly",
            "https://www.googleapis.com/auth/admin.directory.group.member.readonly",
        ]
    )

    def __init__(
        self, client: httpx.Client, *, service_account_json: str, admin_email: str
    ) -> None:
        try:
            info = json.loads(service_account_json)
            self._client_email: str = info["client_email"]
            key = serialization.load_pem_private_key(info["private_key"].encode(), password=None)
            if not isinstance(key, rsa.RSAPrivateKey):
                raise ValueError("private_key is not an RSA key")
            self._private_key = key
        except (ValueError, KeyError, TypeError) as exc:
            raise DirectoryConnectorError(f"invalid Google service account: {exc}") from exc
        self._client = client
        self._admin_email = admin_email

    @staticmethod
    def _b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    def _assertion(self) -> str:
        now = int(time.time())
        header = self._b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = self._b64(
            json.dumps(
                {
                    "iss": self._client_email,
                    "sub": self._admin_email,
                    "scope": self.SCOPES,
                    "aud": self.TOKEN_URI,
                    "iat": now,
                    "exp": now + 3600,
                }
            ).encode()
        )
        signing_input = header + b"." + claims
        signature = self._private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return (signing_input + b"." + self._b64(signature)).decode()

    def _pages(self, url: str, key: str, headers: dict[str, str]) -> Iterator[dict[str, Any]]:
        page_token: str | None = None
        while True:
            params = {"maxResults": "200", "customer": "my_customer"}
            if page_token:
                params["pageToken"] = page_token
            page = _get_json(self._client, url, headers=headers, params=params)
            yield from page.get(key, [])
            page_token = page.get("nextPageToken")
            if not page_token:
                return

    def fetch(self) -> DirectorySnapshot:
        token = _post_token(
            self._client,
            self.TOKEN_URI,
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": self._assertion(),
            },
        )
        headers = {"Authorization": f"Bearer {token}"}

        users: dict[str, DirUser] = {}
        for raw in self._pages(f"{self.API}/users", "users", headers):
            name = raw.get("name", {})
            users[raw["id"]] = DirUser(
                external_id=raw["id"],
                email=raw["primaryEmail"].lower(),
                given_name=name.get("givenName", ""),
                family_name=name.get("familyName", ""),
                active=not raw.get("suspended", False),
            )

        groups: list[DirGroup] = []
        for raw in self._pages(f"{self.API}/groups", "groups", headers):
            groups.append(
                DirGroup(raw["id"], raw.get("name") or raw["email"], raw.get("description") or "")
            )
            members_url = f"{self.API}/groups/{raw['id']}/members"
            for member in self._pages(members_url, "members", headers):
                if member.get("type") == "USER" and member.get("id") in users:
                    users[member["id"]].group_ids.add(raw["id"])
        return DirectorySnapshot(users=list(users.values()), groups=groups)


# Per remote source: the non-secret fields kept in clear, and the single
# secret kept only as AES-GCM ciphertext under the runtime master key.
REMOTE_SOURCES: dict[str, tuple[tuple[str, ...], str]] = {
    "entra": (("tenant_id", "client_id"), "client_secret"),
    "google": (("admin_email",), "service_account_json"),
}


def build_remote_connector(
    config: DirectoryConnectorConfig, master_key: str, client: httpx.Client
) -> DirectoryConnector:
    if not master_key:
        raise DirectoryConnectorError("LCIT_SIGN_MASTER_KEY is not configured")
    if not config.encrypted_secret:
        raise DirectoryConnectorError(f"connector {config.source!r} has no secret configured")
    try:
        secret = decrypt_secret(master_key, config.encrypted_secret)
    except Exception as exc:  # wrong master key / corrupted ciphertext
        raise DirectoryConnectorError(f"cannot decrypt {config.source!r} secret") from exc
    fields: dict[str, str] = json.loads(config.settings_json)
    if config.source == "entra":
        return EntraConnector(
            client,
            tenant_id=fields.get("tenant_id", ""),
            client_id=fields.get("client_id", ""),
            client_secret=secret,
        )
    return GoogleWorkspaceConnector(
        client, service_account_json=secret, admin_email=fields.get("admin_email", "")
    )
