"""An LDAP directory (OpenLDAP, 389 DS, Active Directory…), read with a read-only account."""

from __future__ import annotations

import re
import ssl
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx
from ldap3 import BASE, NONE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.dn import parse_dn

from lcit_sign.services.connector_fields import FieldSpec
from lcit_sign.services.directory.base import (
    ConnectorSpec,
    DirectoryAttribute,
    DirectoryConnector,
    DirectoryConnectorError,
    DirectorySnapshot,
    DirGroup,
    DirUser,
    describe_attributes,
    ensure_custom_teams_present,
    split_name,
    team_selector_field,
    teams_from_values,
)
from lcit_sign.services.ssrf import OutboundTargetError, validate_outbound_target

TEAM_SELECTORS = (
    ("groups", "Les groupes LDAP"),
    ("attribute", "Un attribut de chaque personne (ex : department)"),
    ("container", "Le dossier (OU) où se trouve la personne"),
    ("custom_attribute", "Autre attribut"),
)
LDAP_PORTS = frozenset({389, 636})
PAGE = 500
DISCOVERY_SAMPLE_SIZE = 50
MAX_DISCOVERY_ATTRIBUTES = 300
SENSITIVE_ATTRIBUTE = re.compile(
    r"(?:password|passwd|credential|secret|token|private.?key|certificate|jpegphoto|thumbnailphoto)",
    re.IGNORECASE,
)
ATTRIBUTE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9;-]{0,127}$")


def _norm(dn: str) -> str:
    """A DN written one way or another (spaces around commas and equals, case) compares equal."""
    return re.sub(r"\s*([=,])\s*", r"\1", dn.strip()).lower()


def _first(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return "" if value is None else str(value)


def _single_team_value(value: Any) -> Any:
    """LDAP returns every attribute as a list; only a single string can name one team."""
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    return value


def _container(dn: str) -> str:
    """The first OU above an entry: uid=jd,ou=Comptabilite,ou=People,dc=corp -> Comptabilite."""
    try:
        parts = parse_dn(dn)[1:]
    except Exception:
        return ""
    for attribute, value, _ in parts:
        if attribute.lower() == "ou":
            return str(value)
    return ""


class LdapConnector:
    source = "ldap"

    def __init__(
        self,
        *,
        server_url: str,
        bind_dn: str,
        bind_password: str,
        base_dn: str,
        user_filter: str = "(objectClass=person)",
        group_filter: str = "",
        member_attribute: str = "member",
        id_attribute: str = "entryUUID",
        email_attribute: str = "mail",
        given_name_attribute: str = "givenName",
        family_name_attribute: str = "sn",
        team_selector: str = "groups",
        team_attribute: str = "",
        custom_team_attribute: str = "",
        custom_team_groups: bool = False,
        start_tls: bool = False,
        connection_factory: Callable[[], Connection] | None = None,
        paged: bool = True,
    ) -> None:
        self._server_url = server_url
        self._bind_dn = bind_dn
        self._bind_password = bind_password
        self._base_dn = base_dn
        self._user_filter = user_filter or "(objectClass=person)"
        self._group_filter = group_filter
        self._member = member_attribute or "member"
        self._id = id_attribute or "entryUUID"
        self._email = email_attribute or "mail"
        self._given = given_name_attribute or "givenName"
        self._family = family_name_attribute or "sn"
        self._groups = (
            team_selector in ("groups", "both")
            or (team_selector == "custom_attribute" and custom_team_groups)
        ) and bool(group_filter)
        self._by_attribute = team_attribute if team_selector in ("attribute", "both") else ""
        self._by_container = team_selector == "container"
        self._custom_team_attribute = (
            custom_team_attribute if team_selector == "custom_attribute" else ""
        )
        if self._custom_team_attribute and not ATTRIBUTE_NAME.fullmatch(
            self._custom_team_attribute
        ):
            raise DirectoryConnectorError("Attribut personnalisé LDAP invalide.")
        self._start_tls = start_tls
        self._factory = connection_factory
        self._paged = paged

    def _connect(self) -> Connection:
        if self._factory is not None:
            return self._factory()
        url = urlparse(self._server_url)
        host = url.hostname or ""
        port = url.port or (636 if url.scheme == "ldaps" else 389)
        try:
            validate_outbound_target(host, port, allow_ports=LDAP_PORTS)
        except OutboundTargetError as exc:
            raise DirectoryConnectorError(f"Serveur LDAP refusé : {exc}") from exc
        secure = url.scheme == "ldaps" or self._start_tls
        # The server's certificate is always checked: the bind password goes over this link.
        tls = Tls(validate=ssl.CERT_REQUIRED, version=ssl.PROTOCOL_TLS_CLIENT) if secure else None
        server = Server(
            host,
            port=port,
            use_ssl=url.scheme == "ldaps",
            tls=tls,
            get_info=NONE,
            connect_timeout=15,
        )
        try:
            connection = Connection(
                server,
                user=self._bind_dn,
                password=self._bind_password,
                receive_timeout=60,
                raise_exceptions=True,
            )
            if self._start_tls and url.scheme != "ldaps":
                connection.open()
                connection.start_tls()
            connection.bind()
        except LDAPException as exc:
            raise DirectoryConnectorError(self._describe(exc)) from exc
        return connection

    @staticmethod
    def _describe(exc: Exception) -> str:
        text = type(exc).__name__
        if "InvalidCredentials" in text:
            return "Le compte de liaison est refusé : vérifiez son DN et son mot de passe."
        if "SocketOpen" in text or "Timeout" in text:
            return "Le serveur LDAP ne répond pas : vérifiez l'adresse, le port et le pare-feu."
        if "Tls" in text or "SSL" in text or "Certificate" in text:
            return (
                "La connexion sécurisée a échoué : le certificat du serveur LDAP n'est pas "
                "reconnu (autorité interne à installer sur le serveur LCIT Sign ?)."
            )
        return f"Erreur LDAP ({text})."

    def _search(
        self, connection: Connection, flt: str, attributes: list[str]
    ) -> list[dict[str, Any]]:
        try:
            if self._paged:
                found = connection.extend.standard.paged_search(
                    self._base_dn,
                    flt,
                    search_scope=SUBTREE,
                    attributes=attributes,
                    paged_size=PAGE,
                    generator=True,
                )
            else:
                connection.search(self._base_dn, flt, search_scope=SUBTREE, attributes=attributes)
                found = connection.response or []
            return [e for e in found if e.get("type", "searchResEntry") == "searchResEntry"]
        except LDAPException as exc:
            raise DirectoryConnectorError(self._describe(exc)) from exc

    def _search_sample(
        self, connection: Connection, flt: str, attributes: list[str], limit: int
    ) -> list[dict[str, Any]]:
        """Read at most `limit` entries and stop a paged cursor once enough arrive."""
        try:
            if not self._paged:
                connection.search(
                    self._base_dn,
                    flt,
                    search_scope=SUBTREE,
                    attributes=attributes,
                    size_limit=limit,
                )
                found = connection.response or []
            else:
                found = connection.extend.standard.paged_search(
                    self._base_dn,
                    flt,
                    search_scope=SUBTREE,
                    attributes=attributes,
                    paged_size=min(PAGE, limit),
                    generator=True,
                )
            entries: list[dict[str, Any]] = []
            for entry in found:
                if entry.get("type", "searchResEntry") != "searchResEntry":
                    continue
                entries.append(entry)
                if len(entries) >= limit:
                    break
            return entries
        except LDAPException as exc:
            raise DirectoryConnectorError(self._describe(exc)) from exc

    @staticmethod
    def _schema_attributes(connection: Connection) -> set[str]:
        """Read attribute names from the advertised subschema when the bind can access it."""
        try:
            if not connection.search(
                "", "(objectClass=*)", search_scope=BASE, attributes=["subschemaSubentry"]
            ):
                return set()
            root = (connection.response or [{}])[0].get("attributes", {})
            schema_dn = _first(root.get("subschemaSubentry"))
            if not schema_dn or not connection.search(
                schema_dn,
                "(objectClass=*)",
                search_scope=BASE,
                attributes=["attributeTypes"],
            ):
                return set()
            raw_values = (
                (connection.response or [{}])[0].get("attributes", {}).get("attributeTypes", [])
            )
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            names: set[str] = set()
            for raw in values:
                match = re.search(r"\bNAME\s+(?:\(\s*)?'([^']+)'", str(raw), re.IGNORECASE)
                if match:
                    name = match.group(1)
                    if ATTRIBUTE_NAME.fullmatch(name) and not SENSITIVE_ATTRIBUTE.search(name):
                        names.add(name)
            return names
        except LDAPException:
            return set()

    def discover_attributes(self) -> list[DirectoryAttribute]:
        """Sample a bounded set of users; never return credentials or common secret fields."""
        connection = self._connect()
        try:
            sample = self._search_sample(
                connection, self._user_filter, ["*"], DISCOVERY_SAMPLE_SIZE
            )
            observed: dict[str, list[Any]] = {}
            for entry in sample:
                attrs = entry.get("attributes", {})
                for name, value in attrs.items():
                    if ATTRIBUTE_NAME.fullmatch(name) and not SENSITIVE_ATTRIBUTE.search(name):
                        observed.setdefault(name, []).append(value)
            schema_names = self._schema_attributes(connection)
            names = sorted(set(observed) | schema_names)[:MAX_DISCOVERY_ATTRIBUTES]
            values = {name: observed.get(name, [None] * len(sample)) for name in names}
            return describe_attributes(
                values,
                sample_count=len(sample),
                available_by_attribute={
                    name: name in schema_names or name in observed for name in names
                },
            )
        finally:
            try:
                connection.unbind()
            except LDAPException:
                pass

    def fetch(self, *, sample_size: int | None = None) -> DirectorySnapshot:
        connection = self._connect()
        try:
            user_attributes = [
                self._id,
                self._email,
                self._given,
                self._family,
                "displayName",
                "cn",
                "userAccountControl",
                "nsAccountLock",
            ]
            if self._by_attribute:
                user_attributes.append(self._by_attribute)
            if self._custom_team_attribute:
                user_attributes.append(self._custom_team_attribute)
            users: dict[str, DirUser] = {}
            dn_to_user: dict[str, str] = {}
            team_values: dict[str, Any] = {}
            user_entries = (
                self._search_sample(connection, self._user_filter, user_attributes, sample_size)
                if sample_size is not None
                else self._search(connection, self._user_filter, user_attributes)
            )
            for entry in user_entries:
                attrs = entry.get("attributes", {})
                email = _first(attrs.get(self._email)).lower()
                if not email:
                    continue
                dn = _norm(entry["dn"])
                external_id = _first(attrs.get(self._id)) or dn
                given, family = _first(attrs.get(self._given)), _first(attrs.get(self._family))
                if not given and not family:
                    given, family = split_name(
                        _first(attrs.get("displayName")) or _first(attrs.get("cn")) or email
                    )
                # Active Directory flags a disabled account in bit 2; 389 DS uses nsAccountLock.
                uac = _first(attrs.get("userAccountControl"))
                disabled = (uac.isdigit() and int(uac) & 2 == 2) or (
                    _first(attrs.get("nsAccountLock")).lower() == "true"
                )
                users[external_id] = DirUser(external_id, email, given, family, active=not disabled)
                dn_to_user[dn] = external_id
                user_attrs: dict[str, Any] = {}
                if self._custom_team_attribute:
                    custom_value = attrs.get(self._custom_team_attribute)
                    user_attrs[self._custom_team_attribute] = custom_value
                    team_values[external_id] = _single_team_value(custom_value)
                if self._by_attribute:
                    team_values[external_id] = _first(attrs.get(self._by_attribute))
                elif self._by_container:
                    team_values[external_id] = _container(entry["dn"])
                users[external_id].attributes = user_attrs

            groups: list[DirGroup] = []
            if self._groups:
                by_dn: dict[str, DirGroup] = {}
                members_of: dict[str, list[str]] = {}
                group_attributes = ["cn", "description", self._member]
                group_entries = (
                    self._search_sample(
                        connection, self._group_filter, group_attributes, sample_size
                    )
                    if sample_size is not None
                    else self._search(connection, self._group_filter, group_attributes)
                )
                for entry in group_entries:
                    attrs = entry.get("attributes", {})
                    dn = _norm(entry["dn"])
                    group = DirGroup(
                        dn, _first(attrs.get("cn")) or dn, _first(attrs.get("description"))
                    )
                    by_dn[dn] = group
                    groups.append(group)
                    raw = attrs.get(self._member) or []
                    members_of[dn] = [_norm(m) for m in (raw if isinstance(raw, list) else [raw])]
                for dn, members in members_of.items():
                    for member in members:
                        if member in dn_to_user:
                            users[dn_to_user[member]].group_ids.add(dn)
                        elif member in by_dn:
                            by_dn[dn].child_group_ids.add(member)
            snapshot = DirectorySnapshot(users=list(users.values()), groups=groups)
            if team_values:
                prefix = (
                    f"team-{self._custom_team_attribute}" if self._custom_team_attribute else "team"
                )
                teams_from_values(snapshot, team_values, prefix=prefix)
                if self._custom_team_attribute:
                    ensure_custom_teams_present(snapshot, prefix, sample_size=sample_size)
            return snapshot
        finally:
            try:
                connection.unbind()
            except LDAPException:
                pass

    def fetch_sample(self) -> DirectorySnapshot:
        """Preview at most one bounded page of users and groups."""
        return self.fetch(sample_size=DISCOVERY_SAMPLE_SIZE)


def validate(fields: dict[str, str], secret: str | None) -> None:
    url = urlparse(fields.get("server_url", "").strip())
    if url.scheme not in ("ldap", "ldaps") or not url.hostname:
        raise ValueError(
            "L'adresse du serveur doit commencer par ldaps:// (ou ldap://), "
            "par exemple ldaps://ldap.entreprise.fr:636."
        )
    if url.scheme == "ldap" and fields.get("start_tls") != "yes":
        raise ValueError(
            "Avec ldap:// le mot de passe du compte de liaison circulerait en clair : "
            "utilisez ldaps://, ou activez StartTLS."
        )
    port = url.port or (636 if url.scheme == "ldaps" else 389)
    try:
        validate_outbound_target(url.hostname, port, allow_ports=LDAP_PORTS)
    except OutboundTargetError as exc:
        raise ValueError(f"Serveur LDAP refusé : {exc}") from exc
    for name, label in (("bind_dn", "Compte de liaison"), ("base_dn", "Base de recherche")):
        if "=" not in fields.get(name, ""):
            raise ValueError(
                f"« {label} » doit être un DN, par exemple "
                + (
                    "cn=lcit-sign,ou=services,dc=entreprise,dc=fr"
                    if name == "bind_dn"
                    else "dc=entreprise,dc=fr"
                )
                + "."
            )
    for name in ("user_filter", "group_filter"):
        value = fields.get(name, "").strip()
        if value and not (value.startswith("(") and value.endswith(")")):
            raise ValueError(
                "Un filtre LDAP s'écrit entre parenthèses, par exemple (objectClass=person)."
            )
    if fields.get("team_selector") in ("attribute", "both") and not fields.get("team_attribute"):
        raise ValueError(
            "Indiquez l'attribut qui donne le nom de l'équipe (par exemple department)."
        )
    if fields.get("team_selector") == "custom_attribute" and not ATTRIBUTE_NAME.fullmatch(
        fields.get("custom_team_attribute", "")
    ):
        raise ValueError("Découvrez puis choisissez un attribut d'équipe disponible.")
    if (
        fields.get("team_selector") in ("groups", "both")
        and not fields.get("group_filter", "").strip()
    ):
        raise ValueError("Pour lire les groupes, indiquez le filtre des groupes.")


def build(client: httpx.Client, fields: dict[str, str], secret: str) -> DirectoryConnector:
    return LdapConnector(
        server_url=fields["server_url"],
        bind_dn=fields["bind_dn"],
        bind_password=secret,
        base_dn=fields["base_dn"],
        user_filter=fields.get("user_filter", ""),
        group_filter=fields.get("group_filter", ""),
        member_attribute=fields.get("member_attribute", ""),
        id_attribute=fields.get("id_attribute", ""),
        email_attribute=fields.get("email_attribute", ""),
        given_name_attribute=fields.get("given_name_attribute", ""),
        family_name_attribute=fields.get("family_name_attribute", ""),
        team_selector=fields.get("team_selector", "groups"),
        team_attribute=fields.get("team_attribute", ""),
        custom_team_attribute=fields.get("custom_team_attribute", ""),
        custom_team_groups=fields.get("custom_team_groups") == "true",
        start_tls=fields.get("start_tls") == "yes",
    )


SPEC = ConnectorSpec(
    source="ldap",
    label="LDAP / Active Directory",
    description=(
        "Lit les utilisateurs et les groupes d'un annuaire LDAP (OpenLDAP, 389 DS, Active "
        "Directory…) avec un compte de service en lecture seule. La connexion est chiffrée et le "
        "certificat du serveur est toujours vérifié."
    ),
    fields=(
        FieldSpec(
            "server_url",
            "Adresse du serveur",
            "L'adresse de l'annuaire. ldaps:// (port 636) chiffre la connexion ; "
            "ldap:// (port 389) "
            "n'est accepté qu'avec StartTLS.",
            "ldaps://ldap.entreprise.fr:636",
        ),
        FieldSpec(
            "start_tls",
            "StartTLS",
            "Chiffrer une connexion ldap:// avec StartTLS (inutile avec ldaps://).",
            "non",
            kind="select",
            options=(("no", "Non"), ("yes", "Oui")),
            default="no",
            required=False,
        ),
        FieldSpec(
            "bind_dn",
            "Compte de liaison (DN)",
            "Le DN du compte de service en lecture seule que LCIT Sign utilise pour "
            "lire l'annuaire. "
            "Le mot de passe se saisit plus bas.",
            "cn=lcit-sign,ou=services,dc=entreprise,dc=fr",
        ),
        FieldSpec(
            "base_dn",
            "Base de recherche (DN)",
            "Le point de l'annuaire à partir duquel chercher les personnes et les groupes.",
            "dc=entreprise,dc=fr",
        ),
        FieldSpec(
            "user_filter",
            "Filtre des personnes",
            "Quelles entrées sont des utilisateurs. Par défaut toutes les personnes ; sous Active "
            "Directory : (&(objectClass=user)(objectCategory=person)).",
            "(objectClass=person)",
            default="(objectClass=person)",
            required=False,
        ),
        FieldSpec(
            "email_attribute",
            "Attribut e-mail",
            "Le champ qui contient l'adresse e-mail (sert à reconnaître la personne "
            "à sa connexion SSO).",
            "mail",
            default="mail",
            required=False,
        ),
        FieldSpec(
            "given_name_attribute",
            "Attribut prénom",
            "Le champ LDAP qui contient le prénom de la personne.",
            "givenName",
            default="givenName",
            required=False,
        ),
        FieldSpec(
            "family_name_attribute",
            "Attribut nom",
            "Le champ LDAP qui contient le nom de famille de la personne.",
            "sn",
            default="sn",
            required=False,
        ),
        FieldSpec(
            "id_attribute",
            "Attribut identifiant stable",
            "Un champ qui ne change jamais pour une personne, pour la reconnaître même si elle "
            "change de nom ou de dossier. OpenLDAP : entryUUID ; Active Directory : objectGUID.",
            "entryUUID",
            default="entryUUID",
            required=False,
        ),
        team_selector_field(options=TEAM_SELECTORS),
        FieldSpec(
            "custom_team_attribute",
            "Attribut de rattachement à l'équipe",
            "Attribut découvert dans l'annuaire et utilisé comme nom d'équipe.",
            "Choisissez un attribut découvert",
            kind="select",
            options=(),
            default="",
            required=False,
        ),
        FieldSpec(
            "custom_team_groups",
            "Inclure aussi les groupes LDAP",
            "Ajoute les groupes natifs en complément des équipes créées depuis l'attribut.",
            "Non",
            kind="checkbox",
            default="false",
            required=False,
        ),
        FieldSpec(
            "group_filter",
            "Filtre des groupes",
            "Quelles entrées sont des groupes (une équipe = un groupe). "
            "Laissez vide si les équipes "
            "ne viennent pas des groupes.",
            "(|(objectClass=groupOfNames)(objectClass=group))",
            required=False,
        ),
        FieldSpec(
            "member_attribute",
            "Attribut des membres",
            "Dans un groupe, le champ qui liste ses membres (leurs DN).",
            "member",
            default="member",
            required=False,
        ),
        FieldSpec(
            "team_attribute",
            "Attribut qui donne l'équipe",
            "Le champ de chaque personne dont la valeur est le nom de l'équipe. "
            "Utilisé si vous avez "
            "choisi « un attribut ».",
            "department",
            required=False,
        ),
    ),
    secret=FieldSpec(
        "bind_password",
        "Mot de passe du compte de liaison",
        "Le mot de passe du compte de service en lecture seule. Chiffré ici, jamais réaffiché.",
        "",
        kind="password",
    ),
    validate=validate,
    build=build,
)
