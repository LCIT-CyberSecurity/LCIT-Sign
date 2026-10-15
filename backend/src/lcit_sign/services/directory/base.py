"""What every directory connector shares: the snapshot it returns, how nested groups
are flattened, and the description of its settings (which the admin page renders as a form,
with a help bubble per field)."""

from __future__ import annotations

import unicodedata
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
    # Provider properties read for team mapping. Kept in memory for the snapshot only.
    attributes: dict[str, Any] = field(default_factory=dict)


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
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DirectoryAttribute:
    """A safe-to-display attribute found in a bounded directory sample."""

    name: str
    label: str
    data_type: str
    available: bool
    populated_count: int
    sample_count: int
    examples: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "data_type": self.data_type,
            "available": self.available,
            "populated_count": self.populated_count,
            "sample_count": self.sample_count,
            "population_ratio": (
                round(self.populated_count / self.sample_count, 4) if self.sample_count else 0.0
            ),
            "examples": list(self.examples),
        }


def describe_attributes(
    values_by_attribute: dict[str, list[Any]],
    labels: dict[str, str] | None = None,
    *,
    sample_count: int,
    available_by_attribute: dict[str, bool] | None = None,
) -> list[DirectoryAttribute]:
    """Summarize already-bounded, provider-read values without retaining full records."""
    result: list[DirectoryAttribute] = []
    for name, values in sorted(values_by_attribute.items()):
        non_empty = [value for value in values if value is not None and value != "" and value != []]
        types = {type(value).__name__ for value in non_empty}
        data_type = next(iter(types)) if len(types) == 1 else "mixed" if types else "string"
        examples: list[str] = []
        for value in non_empty:
            rendered = (
                ", ".join(str(part) for part in value) if isinstance(value, list) else str(value)
            )
            rendered = " ".join(rendered.split())
            if rendered and rendered not in examples:
                examples.append(rendered[:120])
            if len(examples) == 3:
                break
        result.append(
            DirectoryAttribute(
                name=name,
                label=(labels or {}).get(name, name),
                data_type=data_type,
                available=(available_by_attribute or {}).get(
                    name, bool(values) and any(value is not None for value in values)
                ),
                populated_count=len(non_empty),
                sample_count=sample_count,
                examples=tuple(examples),
            )
        )
    return result


def value_at_path(record: Any, path: str) -> Any:
    """Read a provider-neutral dotted path; arrays use their first object entry."""
    value = record
    for part in path.split("."):
        if isinstance(value, list):
            value = value[0] if value else None
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def path_exists(record: Any, path: str) -> bool:
    """Whether a provider response contains a path, even if its value is empty."""
    parts = path.split(".")
    value = record
    for part in parts[:-1]:
        if isinstance(value, list):
            value = value[0] if value else None
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    if isinstance(value, list):
        value = value[0] if value else None
    return isinstance(value, dict) and parts[-1] in value


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
    ("custom_attribute", "Autre attribut"),
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
    snapshot: DirectorySnapshot, value_by_user: dict[str, Any], *, prefix: str = "team"
) -> None:
    """Make one team per distinct value (the "Comptabilité" department → a group with every
    person who has it). Added to the snapshot, next to the directory's real groups."""
    members: dict[str, list[DirUser]] = {}
    display_by_key: dict[str, str] = {}
    by_id = {u.external_id: u for u in snapshot.users}
    for user_id, raw in value_by_user.items():
        if not isinstance(raw, str):
            if raw is not None:
                snapshot.warnings.append(
                    "Une valeur d'équipe a été ignorée : une valeur unique en texte est attendue."
                )
            continue
        value = unicodedata.normalize("NFC", " ".join(raw.split()))
        if value and user_id in by_id:
            key = value.casefold()
            display_by_key[key] = min(display_by_key.get(key, value), value)
            members.setdefault(key, []).append(by_id[user_id])
    for key, people in sorted(members.items()):
        value = display_by_key[key]
        group_id = f"{prefix}:{value.lower()}"
        # Existing snapshots may contain duplicate values with case-only differences.
        if any(group.external_id == group_id for group in snapshot.groups):
            snapshot.warnings.append(f"Identifiant d'équipe en collision ignoré : {group_id!r}.")
            continue
        snapshot.groups.append(DirGroup(group_id, value, f"Équipe « {value} »"))
        for person in people:
            person.group_ids.add(group_id)


def ensure_custom_teams_present(
    snapshot: DirectorySnapshot, prefix: str, *, sample_size: int | None
) -> None:
    """Fail a full sync before writes if a newly selected mapping yields no teams.

    Preview samples are allowed to be empty; a full sync must not interpret a missing,
    inaccessible, or entirely blank custom attribute as a request to remove all teams.
    """
    if (
        sample_size is None
        and snapshot.users
        and not any(group.external_id.startswith(f"{prefix}:") for group in snapshot.groups)
    ):
        raise DirectoryConnectorError(
            "Le mapping personnalisé n'a produit aucune équipe ; la synchronisation est annulée."
        )
