"""Microsoft Entra ID (Office 365), read through Microsoft Graph."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx

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
    split_name,
    team_selector_field,
    teams_from_values,
)

_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_DOMAIN = re.compile(r"^(?=.{4,253}$)([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")

# Only these user properties can be read as a team: they are fixed names, so nothing typed
# by an admin ends up inside a Graph query.
TEAM_ATTRIBUTES = (
    ("department", "Service (department)"),
    ("officeLocation", "Bureau (officeLocation)"),
    ("companyName", "Société (companyName)"),
    ("jobTitle", "Fonction (jobTitle)"),
    ("city", "Ville (city)"),
)


class EntraConnector:
    """Microsoft Entra ID via Microsoft Graph, app-only (client
    credentials). Needs User.Read.All, Group.Read.All and
    GroupMember.Read.All application permissions, read-only (spec §22-30).
    """

    source = "entra"
    GRAPH = "https://graph.microsoft.com/v1.0"

    def __init__(
        self,
        client: httpx.Client,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        team_selector: str = "groups",
        team_attribute: str = "department",
    ) -> None:
        self._client = client
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._groups = team_selector in ("groups", "both")
        self._team_attribute = team_attribute if team_selector in ("attribute", "both") else None
        if self._team_attribute and self._team_attribute not in dict(TEAM_ATTRIBUTES):
            raise DirectoryConnectorError(f"Attribut d'équipe inconnu : {team_attribute!r}")

    def _pages(self, url: str, headers: dict[str, str]) -> Iterator[dict[str, Any]]:
        next_url: str | None = url
        while next_url:
            page = get_json(self._client, next_url, headers=headers)
            yield from page.get("value", [])
            next_url = page.get("@odata.nextLink")

    def fetch(self) -> DirectorySnapshot:
        token = post_token(
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
        if self._team_attribute:
            select += f",{self._team_attribute}"
        team_values: dict[str, str] = {}
        for raw in self._pages(f"{self.GRAPH}/users?$select={select}&$top=999", headers):
            email = raw.get("mail") or raw.get("userPrincipalName")
            if not email:
                continue
            given = raw.get("givenName") or ""
            family = raw.get("surname") or ""
            if not given and not family:
                given, family = split_name(raw.get("displayName") or email)
            if self._team_attribute:
                team_values[raw["id"]] = str(raw.get(self._team_attribute) or "")
            users[raw["id"]] = DirUser(
                external_id=raw["id"],
                email=email.lower(),
                given_name=given,
                family_name=family,
                active=bool(raw.get("accountEnabled", True)),
            )

        groups: list[DirGroup] = []
        for raw in (
            self._pages(f"{self.GRAPH}/groups?$select=id,displayName,description&$top=999", headers)
            if self._groups
            else ()
        ):
            name = raw.get("displayName") or raw["id"]
            groups.append(DirGroup(raw["id"], name, raw.get("description") or ""))
            members_url = f"{self.GRAPH}/groups/{raw['id']}/members?$select=id&$top=999"
            for member in self._pages(members_url, headers):
                kind = member.get("@odata.type")
                if kind == "#microsoft.graph.user" and member["id"] in users:
                    users[member["id"]].group_ids.add(raw["id"])
                elif kind == "#microsoft.graph.group":
                    groups[-1].child_group_ids.add(member["id"])
        snapshot = DirectorySnapshot(users=list(users.values()), groups=groups)
        if self._team_attribute:
            teams_from_values(snapshot, team_values, prefix=f"team-{self._team_attribute}")
        return snapshot


def validate(fields: dict[str, str], secret: str | None) -> None:
    """The classic mix-ups, caught while typing: a secret in the application-id field, an id
    given as the secret. Anything else is left to Microsoft's own answer."""
    tenant, client = fields.get("tenant_id", "").strip(), fields.get("client_id", "").strip()
    if not (_GUID.match(tenant) or _DOMAIN.match(tenant)):
        raise ValueError(
            "L'ID du tenant doit ressembler à 73405479-f042-45d7-8149-c90341261b65 "
            "(Entra → Vue d'ensemble → ID de locataire) ou à votre domaine "
            "(entreprise.onmicrosoft.com)."
        )
    if "~" in client:
        raise ValueError(
            "Ce qui est saisi dans « ID de l'application (client) » ressemble à un "
            "secret : le secret va dans le champ « Secret client »."
        )
    if not _GUID.match(client):
        raise ValueError(
            "L'ID de l'application (client) doit être un code du type "
            "9a8b7c6d-5e4f-4321-b0a9-8c7d6e5f4a3b : page « Vue d'ensemble » de l'application "
            "dans Entra, ligne « ID de l'application (client) »."
        )
    if secret is not None:
        if _GUID.match(secret.strip()):
            raise ValueError(
                "Ceci est un identifiant (ID de secret ou de l'application), pas la valeur du "
                "secret. Dans Entra → Certificats et secrets, copiez la colonne « Valeur » "
                "(une suite d'environ 40 caractères avec un « ~ »)."
            )
        if secret.strip() in (tenant, client):
            raise ValueError("Le secret client ne peut pas être identique à un des identifiants.")
    if fields.get("team_selector") in ("attribute", "both") and fields.get(
        "team_attribute"
    ) not in dict(TEAM_ATTRIBUTES):
        raise ValueError("Choisissez l'attribut qui donne le nom de l'équipe.")


def build(client: httpx.Client, fields: dict[str, str], secret: str) -> DirectoryConnector:
    return EntraConnector(
        client,
        tenant_id=fields.get("tenant_id", ""),
        client_id=fields.get("client_id", ""),
        client_secret=secret,
        team_selector=fields.get("team_selector", "groups"),
        team_attribute=fields.get("team_attribute", "department"),
    )


SPEC = ConnectorSpec(
    source="entra",
    label="Microsoft Entra ID (Office 365)",
    description=(
        "Lit les utilisateurs et les groupes de votre tenant Microsoft, en lecture seule, avec une "
        "application déclarée dans Entra (permissions User.Read.All, Group.Read.All et "
        "GroupMember.Read.All de type Application, avec consentement administrateur)."
    ),
    fields=(
        FieldSpec(
            "tenant_id",
            "ID du tenant",
            "L'identifiant de votre annuaire Microsoft. "
            "Entra → Vue d'ensemble → « ID de locataire » "
            "(ou le nom de votre domaine .onmicrosoft.com).",
            "73405479-f042-45d7-8149-c90341261b65",
        ),
        FieldSpec(
            "client_id",
            "ID de l'application (client)",
            "L'identifiant de l'application que vous avez déclarée : Entra → Inscriptions "
            "d'applications → votre application → « ID de l'application (client) ». Ce n'est ni "
            "l'ID d'objet, ni l'ID du secret.",
            "9a8b7c6d-5e4f-4321-b0a9-8c7d6e5f4a3b",
        ),
        team_selector_field(),
        FieldSpec(
            "team_attribute",
            "Attribut qui donne l'équipe",
            "Le champ de chaque utilisateur Entra dont la valeur est le nom de l'équipe. "
            "Utilisé si vous avez choisi « un attribut » ou « les deux ».",
            "Service (department)",
            kind="select",
            options=TEAM_ATTRIBUTES,
            default="department",
            required=False,
        ),
    ),
    secret=FieldSpec(
        "client_secret",
        "Secret client",
        "La VALEUR du secret créé dans Entra → Certificats et secrets (colonne « Valeur », pas "
        "« ID de secret »). Elle n'est montrée qu'une fois à la création ; ici elle est chiffrée "
        "et jamais réaffichée.",
        "abC8Q~xYzTn3kLw0pQe5vRsU9dFgHjKlMnOpQr",
        kind="password",
    ),
    validate=validate,
    build=build,
)
