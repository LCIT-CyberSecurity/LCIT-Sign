"""Google Workspace, read through the Admin SDK Directory API."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from lcit_sign.services.directory.base import (
    ConnectorSpec,
    DirectoryConnector,
    DirectoryConnectorError,
    DirectorySnapshot,
    DirGroup,
    DirUser,
    FieldSpec,
    get_json,
    post_token,
    team_selector_field,
    teams_from_values,
)

TEAM_ATTRIBUTES = (
    ("orgunit", "Unité d'organisation (OU)"),
    ("department", "Service (champ « Service » de l'utilisateur)"),
)


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
        self,
        client: httpx.Client,
        *,
        service_account_json: str,
        admin_email: str,
        team_selector: str = "groups",
        team_attribute: str = "orgunit",
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
        self._groups = team_selector in ("groups", "both")
        self._team_attribute = team_attribute if team_selector in ("attribute", "both") else None
        if self._team_attribute and self._team_attribute not in dict(TEAM_ATTRIBUTES):
            raise DirectoryConnectorError(f"Attribut d'équipe inconnu : {team_attribute!r}")

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

    def _pages(
        self, url: str, key: str, headers: dict[str, str], **extra: str
    ) -> Iterator[dict[str, Any]]:
        page_token: str | None = None
        while True:
            params = {"maxResults": "200", "customer": "my_customer", **extra}
            if page_token:
                params["pageToken"] = page_token
            page = get_json(self._client, url, headers=headers, params=params)
            yield from page.get(key, [])
            page_token = page.get("nextPageToken")
            if not page_token:
                return

    def fetch(self) -> DirectorySnapshot:
        token = post_token(
            self._client,
            self.TOKEN_URI,
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": self._assertion(),
            },
        )
        headers = {"Authorization": f"Bearer {token}"}

        users: dict[str, DirUser] = {}
        team_values: dict[str, str] = {}
        # The department lives in the user's "organizations", only returned in full projection.
        extra = {"projection": "full"} if self._team_attribute == "department" else {}
        for raw in self._pages(f"{self.API}/users", "users", headers, **extra):
            if self._team_attribute == "orgunit":
                team_values[raw["id"]] = (
                    str(raw.get("orgUnitPath") or "").strip("/").replace("/", " / ")
                )
            elif self._team_attribute == "department":
                orgs = raw.get("organizations") or [{}]
                team_values[raw["id"]] = str(orgs[0].get("department") or "")
            name = raw.get("name", {})
            users[raw["id"]] = DirUser(
                external_id=raw["id"],
                email=raw["primaryEmail"].lower(),
                given_name=name.get("givenName", ""),
                family_name=name.get("familyName", ""),
                active=not raw.get("suspended", False),
            )

        groups: list[DirGroup] = []
        for raw in self._pages(f"{self.API}/groups", "groups", headers) if self._groups else ():
            groups.append(
                DirGroup(raw["id"], raw.get("name") or raw["email"], raw.get("description") or "")
            )
            members_url = f"{self.API}/groups/{raw['id']}/members"
            for member in self._pages(members_url, "members", headers):
                if member.get("type") == "USER" and member.get("id") in users:
                    users[member["id"]].group_ids.add(raw["id"])
                elif member.get("type") == "GROUP" and member.get("id"):
                    groups[-1].child_group_ids.add(member["id"])
        snapshot = DirectorySnapshot(users=list(users.values()), groups=groups)
        if self._team_attribute:
            teams_from_values(snapshot, team_values, prefix=f"team-{self._team_attribute}")
        return snapshot


def validate(fields: dict[str, str], secret: str | None) -> None:
    if "@" not in fields.get("admin_email", ""):
        raise ValueError(
            "L'e-mail de l'administrateur doit être une adresse (admin@votre-domaine.fr)."
        )
    if secret is not None:
        try:
            key = json.loads(secret)
            valid = isinstance(key, dict) and "client_email" in key and "private_key" in key
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "La clé du compte de service doit être le fichier JSON téléchargé "
                "depuis Google Cloud (« client_email » et « private_key »)."
            )
    if fields.get("team_selector") in ("attribute", "both") and fields.get(
        "team_attribute"
    ) not in dict(TEAM_ATTRIBUTES):
        raise ValueError("Choisissez l'attribut qui donne le nom de l'équipe.")


def build(client: httpx.Client, fields: dict[str, str], secret: str) -> DirectoryConnector:
    return GoogleWorkspaceConnector(
        client,
        service_account_json=secret,
        admin_email=fields.get("admin_email", ""),
        team_selector=fields.get("team_selector", "groups"),
        team_attribute=fields.get("team_attribute", "orgunit"),
    )


SPEC = ConnectorSpec(
    source="google",
    label="Google Workspace",
    description=(
        "Lit les utilisateurs et les groupes de votre domaine Google, en lecture seule, avec un "
        "compte de service autorisé par délégation à l'échelle du domaine (consoles Google Cloud "
        "et Admin)."
    ),
    fields=(
        FieldSpec(
            "admin_email",
            "E-mail d'un administrateur",
            "L'adresse d'un administrateur Google Workspace au nom duquel le compte de service "
            "lit l'annuaire (délégation à l'échelle du domaine).",
            "admin@votre-domaine.fr",
        ),
        team_selector_field(),
        FieldSpec(
            "team_attribute",
            "Attribut qui donne l'équipe",
            "Ce qui sert de nom d'équipe pour chaque personne : son unité d'organisation (OU) dans "
            "la console Admin, ou son champ « Service ». "
            "Utilisé si vous avez choisi « un attribut » "
            "ou « les deux ».",
            "Unité d'organisation (OU)",
            kind="select",
            options=TEAM_ATTRIBUTES,
            default="orgunit",
            required=False,
        ),
    ),
    secret=FieldSpec(
        "service_account_json",
        "Clé du compte de service (JSON)",
        "Le contenu du fichier JSON téléchargé depuis Google Cloud (IAM → Comptes de service → "
        "Clés → Créer une clé). Il contient « client_email » et « private_key ». Chiffré ici, "
        "jamais réaffiché.",
        '{"type": "service_account", "client_email": "…", "private_key": "…"}',
        kind="textarea",
    ),
    validate=validate,
    build=build,
)
