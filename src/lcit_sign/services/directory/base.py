"""What every directory connector shares: the snapshot it returns, how nested groups
are flattened, and the description of its settings (which the admin page renders as a form,
with a help bubble per field)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from lcit_sign.services.aad_errors import describe_token_error
from lcit_sign.services.connector_fields import FieldSpec


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
    # Groups that are members of this group (spec §17): their members are
    # members of this one too. Resolved by expand_nested_groups().
    child_group_ids: set[str] = field(default_factory=set)


@dataclass
class DirectorySnapshot:
    users: list[DirUser]
    groups: list[DirGroup]


MAX_GROUP_DEPTH = 10


def expand_nested_groups(
    snapshot: DirectorySnapshot, max_depth: int = MAX_GROUP_DEPTH
) -> list[str]:
    """Make every user a member of the ancestors of their groups (spec §17).

    Each user ends up with each reachable group once (no duplicates); a
    cycle (A contains B contains A) is detected and cut rather than
    followed; chains deeper than `max_depth` stop there. Returns
    human-readable diagnostics for the sync log — group ids only, nothing
    sensitive.
    """
    diagnostics: list[str] = []
    parents: dict[str, set[str]] = {}
    for group in snapshot.groups:
        for child in group.child_group_ids:
            parents.setdefault(child, set()).add(group.external_id)

    known = {g.external_id for g in snapshot.groups}
    reported: set[str] = set()
    for user in snapshot.users:
        resolved = set(user.group_ids)
        frontier = {(g, 0) for g in user.group_ids}
        while frontier:
            current, depth = frontier.pop()
            for parent in parents.get(current, ()):
                if parent not in known or parent in resolved:
                    continue
                if depth + 1 > max_depth:
                    key = f"depth:{parent}"
                    if key not in reported:
                        reported.add(key)
                        diagnostics.append(
                            f"nested group chain too deep, stopped before {parent!r}"
                        )
                    continue
                resolved.add(parent)
                frontier.add((parent, depth + 1))
        user.group_ids = resolved

    # Cycle report (membership stays correct either way: the `resolved`
    # set above never revisits a group, so a loop cannot spin).
    state: dict[str, int] = {}
    children = {g.external_id: g.child_group_ids & known for g in snapshot.groups}

    def visit(node: str, stack: list[str]) -> None:
        state[node] = 1
        for child in children.get(node, ()):
            if state.get(child, 0) == 0:
                visit(child, [*stack, node])
            elif state.get(child) == 1:
                cycle = " -> ".join([*stack, node, child])
                diagnostics.append(f"nested group cycle detected: {cycle}")
        state[node] = 2

    for group_id in children:
        if state.get(group_id, 0) == 0:
            visit(group_id, [])
    return diagnostics


class DirectoryConnector(Protocol):
    source: str

    def fetch(self) -> DirectorySnapshot: ...


def split_name(display_name: str) -> tuple[str, str]:
    given, _, family = display_name.partition(" ")
    return given, family


def get_json(client: httpx.Client, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = client.get(url, **kwargs)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DirectoryConnectorError(f"GET {url.split('?')[0]} failed: {exc}") from exc
    return data


def post_token(client: httpx.Client, url: str, data: dict[str, str]) -> str:
    try:
        response = client.post(url, data=data)
    except httpx.HTTPError as exc:
        raise DirectoryConnectorError(
            f"Impossible de joindre le service d'authentification ({type(exc).__name__})"
        ) from exc
    if response.status_code != 200:
        raise DirectoryConnectorError(describe_token_error(response))
    try:
        return str(response.json()["access_token"])
    except (ValueError, KeyError) as exc:
        raise DirectoryConnectorError("Réponse inattendue du service d'authentification") from exc


@dataclass(frozen=True)
class ConnectorSpec:
    """A connector as the rest of the app sees it: its settings, its one secret, how to
    check what was typed, and how to build it."""

    source: str
    label: str
    description: str
    fields: tuple[FieldSpec, ...]
    secret: FieldSpec
    # Raises ValueError(message in the admin's words) when what was typed cannot work.
    validate: Callable[[dict[str, str], str | None], None]
    build: Callable[[httpx.Client, dict[str, str], str], DirectoryConnector]
    # Optional step-by-step preparation on the provider's side, shown above the form.
    guide: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "description": self.description,
            "fields": [f.payload() for f in self.fields],
            "secret": self.secret.payload(),
            "guide": list(self.guide),
        }

    def with_defaults(self, values: dict[str, str]) -> dict[str, str]:
        """The values typed, completed with each setting's default, nothing else."""
        return {f.name: values.get(f.name, f.default).strip() for f in self.fields}


# How a team (compta, RH, achats…) is read: from the directory's own groups, from an
# attribute of each person (their department…), or both. Each connector says which
# attributes it can read.
TEAM_SELECTORS = (
    ("groups", "Les groupes de l'annuaire"),
    ("attribute", "Un attribut de chaque personne"),
    ("both", "Les deux"),
)


def team_selector_field(*, options: tuple[tuple[str, str], ...] = TEAM_SELECTORS) -> FieldSpec:
    return FieldSpec(
        name="team_selector",
        label="D'où vient le nom de l'équipe ?",
        help=(
            "Les équipes (compta, RH, achats…) servent à cibler une campagne en une fois. "
            "Elles peuvent venir des groupes de l'annuaire, ou d'un champ renseigné sur chaque "
            "personne (son service, son unité d'organisation…)."
        ),
        example="Les groupes de l'annuaire",
        kind="select",
        options=options,
        default="groups",
    )


def teams_from_values(
    snapshot: DirectorySnapshot, value_by_user: dict[str, str], *, prefix: str = "team"
) -> None:
    """Make one team per distinct value (the "Comptabilité" department → a group with every
    person who has it). Added to the snapshot, next to the directory's real groups."""
    members: dict[str, list[DirUser]] = {}
    by_id = {u.external_id: u for u in snapshot.users}
    for user_id, raw in value_by_user.items():
        value = raw.strip()
        if value and user_id in by_id:
            members.setdefault(value, []).append(by_id[user_id])
    for value, people in sorted(members.items()):
        group_id = f"{prefix}:{value.lower()}"
        snapshot.groups.append(DirGroup(group_id, value, f"Équipe « {value} »"))
        for person in people:
            person.group_ids.add(group_id)
