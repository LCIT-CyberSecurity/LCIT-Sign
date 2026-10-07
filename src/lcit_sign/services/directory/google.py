"""Google Workspace, read through the Admin SDK Directory API."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from lcit_sign.services.connector_fields import FieldSpec
from lcit_sign.services.directory.base import (
    ConnectorSpec,
    DirectoryConnector,
    DirectoryConnectorError,
    DirectorySnapshot,
    DirGroup,
    DirUser,
    get_json,
    team_selector_field,
    teams_from_values,
)
from lcit_sign.services.google_auth import GoogleAuthError, ServiceAccount

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
            self._account = ServiceAccount(service_account_json)
        except GoogleAuthError as exc:
            raise DirectoryConnectorError(str(exc)) from exc
        self._client = client
        self._admin_email = admin_email
        self._groups = team_selector in ("groups", "both")
        self._team_attribute = team_attribute if team_selector in ("attribute", "both") else None
        if self._team_attribute and self._team_attribute not in dict(TEAM_ATTRIBUTES):
            raise DirectoryConnectorError(f"Attribut d'équipe inconnu : {team_attribute!r}")

    def _pages(
        self,
        url: str,
        key: str,
        headers: dict[str, str],
        *,
        customer: bool = True,
        extra: dict[str, str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Every page of a list. `customer=my_customer` scopes users.list and groups.list to the
        whole account; members.list takes none (the group already says whose it is)."""
        extra_params = extra or {}
        page_token: str | None = None
        while True:
            params = {"maxResults": "200", **extra_params}
            if customer:
                params["customer"] = "my_customer"
            if page_token:
                params["pageToken"] = page_token
            page = get_json(self._client, url, headers=headers, params=params)
            yield from page.get(key, [])
            page_token = page.get("nextPageToken")
            if not page_token:
                return

    def fetch(self) -> DirectorySnapshot:
        try:
            token = self._account.token(self._client, self.SCOPES, self._admin_email)
        except GoogleAuthError as exc:
            raise DirectoryConnectorError(str(exc)) from exc
        headers = {"Authorization": f"Bearer {token}"}

        users: dict[str, DirUser] = {}
        team_values: dict[str, str] = {}
        # The department lives in the user's "organizations", only returned in full projection.
        extra = {"projection": "full"} if self._team_attribute == "department" else {}
        for raw in self._pages(f"{self.API}/users", "users", headers, extra=extra):
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
            for member in self._pages(members_url, "members", headers, customer=False):
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
    guide=(
        "Console Google Cloud (console.cloud.google.com) : choisissez ou créez un projet, puis "
        "« APIs et services » → « Bibliothèque » → activez « Admin SDK API ».",
        "« IAM et administration » → « Comptes de service » → « Créer un compte de service » "
        "(par exemple lcit-sign-annuaire). Aucun rôle n'est à lui donner dans Google Cloud.",
        "Ouvrez ce compte → onglet « Clés » → « Ajouter une clé » → « Créer une clé » → JSON. "
        "Le fichier téléchargé : collez son contenu dans « Clé du compte de service » ci-dessous.",
        "Notez l'« ID client » du compte de service (un long nombre, sur sa page de détails, "
        "« Paramètres avancés » ou « Détails »).",
        "Console d'administration (admin.google.com), avec un super-administrateur : « Sécurité » "
        "→ « Contrôle des accès et des données » → « Contrôles des API » → « Gérer la délégation "
        "à l'échelle du domaine » → « Ajouter ». Mettez l'ID client noté à l'étape 4 et, comme "
        "champs d'application OAuth (séparés par des virgules) : "
        "https://www.googleapis.com/auth/admin.directory.user.readonly,"
        "https://www.googleapis.com/auth/admin.directory.group.readonly,"
        "https://www.googleapis.com/auth/admin.directory.group.member.readonly",
        "Ci-dessous, « E-mail d'un administrateur » : l'adresse d'un super-administrateur du "
        "domaine (un compte dédié à la lecture de l'annuaire est préférable). Le compte de "
        "service lit l'annuaire en son nom, en lecture seule ; rien n'est modifié.",
        "Enregistrez, puis lancez une synchronisation. Si Google répond « unauthorized_client » : "
        "l'étape 5 n'est pas encore prise en compte (quelques minutes) ou un champ "
        "d'application est mal recopié. Si la création de clé est refusée à l'étape 3, une "
        "politique de votre organisation l'interdit : demandez à son administrateur de l'autoriser.",  # noqa: E501
    ),
)
