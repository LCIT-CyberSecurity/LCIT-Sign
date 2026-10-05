from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.models.directory import DirectorySyncRun, Group, GroupMembership
from lcit_sign.models.user import User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.directory_connectors import (
    DirectoryConnector,
    DirectoryConnectorError,
    DirectorySnapshot,
    DirGroup,
    DirUser,
)

SOURCE = "local"  # the bundled fictional directory

GROUPS = ["Direction", "RH", "Comptabilite", "Sales", "IT", "Consultants"]


class _DirectoryUser(TypedDict):
    external_id: str
    email: str
    given_name: str
    family_name: str
    group: str


# A fictional organisation for CrashTests (spec §115) — ~24 users across 6
# groups. The first user of each group deliberately matches one of
# mock_oidc's test identities (same external_id/email), so logging in as
# that person exercises the SSO<->directory reconciliation path for real
# (see api/auth.py's callback).
LOCAL_USERS: list[_DirectoryUser] = [
    {"external_id": "u-direction-1", "email": "alice.martin@lcit-test.local", "given_name": "Alice", "family_name": "Martin", "group": "Direction"},  # noqa: E501
    {"external_id": "u-direction-2", "email": "gabriel.lefevre@lcit-test.local", "given_name": "Gabriel", "family_name": "Lefevre", "group": "Direction"},  # noqa: E501
    {"external_id": "u-direction-3", "email": "helene.moreau@lcit-test.local", "given_name": "Helene", "family_name": "Moreau", "group": "Direction"},  # noqa: E501
    {"external_id": "u-direction-4", "email": "isabelle.roux@lcit-test.local", "given_name": "Isabelle", "family_name": "Roux", "group": "Direction"},  # noqa: E501
    {"external_id": "u-rh-1", "email": "bob.dupont@lcit-test.local", "given_name": "Bob", "family_name": "Dupont", "group": "RH"},  # noqa: E501
    {"external_id": "u-rh-2", "email": "julien.fontaine@lcit-test.local", "given_name": "Julien", "family_name": "Fontaine", "group": "RH"},  # noqa: E501
    {"external_id": "u-rh-3", "email": "karine.girard@lcit-test.local", "given_name": "Karine", "family_name": "Girard", "group": "RH"},  # noqa: E501
    {"external_id": "u-rh-4", "email": "louis.bonnet@lcit-test.local", "given_name": "Louis", "family_name": "Bonnet", "group": "RH"},  # noqa: E501
    {"external_id": "u-compta-1", "email": "charlie.durand@lcit-test.local", "given_name": "Charlie", "family_name": "Durand", "group": "Comptabilite"},  # noqa: E501
    {"external_id": "u-compta-2", "email": "manon.faure@lcit-test.local", "given_name": "Manon", "family_name": "Faure", "group": "Comptabilite"},  # noqa: E501
    {"external_id": "u-compta-3", "email": "nicolas.blanc@lcit-test.local", "given_name": "Nicolas", "family_name": "Blanc", "group": "Comptabilite"},  # noqa: E501
    {"external_id": "u-compta-4", "email": "olivia.henry@lcit-test.local", "given_name": "Olivia", "family_name": "Henry", "group": "Comptabilite"},  # noqa: E501
    {"external_id": "u-sales-1", "email": "diane.leroy@lcit-test.local", "given_name": "Diane", "family_name": "Leroy", "group": "Sales"},  # noqa: E501
    {"external_id": "u-sales-2", "email": "pierre.garcia@lcit-test.local", "given_name": "Pierre", "family_name": "Garcia", "group": "Sales"},  # noqa: E501
    {"external_id": "u-sales-3", "email": "quentin.robert@lcit-test.local", "given_name": "Quentin", "family_name": "Robert", "group": "Sales"},  # noqa: E501
    {"external_id": "u-sales-4", "email": "rachel.simon@lcit-test.local", "given_name": "Rachel", "family_name": "Simon", "group": "Sales"},  # noqa: E501
    {"external_id": "u-it-1", "email": "erwan.petit@lcit-test.local", "given_name": "Erwan", "family_name": "Petit", "group": "IT"},  # noqa: E501
    {"external_id": "u-it-2", "email": "sophie.michel@lcit-test.local", "given_name": "Sophie", "family_name": "Michel", "group": "IT"},  # noqa: E501
    {"external_id": "u-it-3", "email": "thomas.caron@lcit-test.local", "given_name": "Thomas", "family_name": "Caron", "group": "IT"},  # noqa: E501
    {"external_id": "u-it-4", "email": "valerie.andre@lcit-test.local", "given_name": "Valerie", "family_name": "Andre", "group": "IT"},  # noqa: E501
    {"external_id": "u-consultants-1", "email": "fatima.benali@lcit-test.local", "given_name": "Fatima", "family_name": "Benali", "group": "Consultants"},  # noqa: E501
    {"external_id": "u-consultants-2", "email": "william.perrin@lcit-test.local", "given_name": "William", "family_name": "Perrin", "group": "Consultants"},  # noqa: E501
    {"external_id": "u-consultants-3", "email": "yasmine.roche@lcit-test.local", "given_name": "Yasmine", "family_name": "Roche", "group": "Consultants"},  # noqa: E501
    {"external_id": "u-consultants-4", "email": "zoe.gauthier@lcit-test.local", "given_name": "Zoe", "family_name": "Gauthier", "group": "Consultants"},  # noqa: E501
]


class LocalConnector:
    source = SOURCE

    def fetch(self) -> DirectorySnapshot:
        return DirectorySnapshot(
            groups=[DirGroup(external_id=name, name=name) for name in GROUPS],
            users=[
                DirUser(
                    external_id=e["external_id"],
                    email=e["email"],
                    given_name=e["given_name"],
                    family_name=e["family_name"],
                    group_ids={e["group"]},
                )
                for e in LOCAL_USERS
            ],
        )


def sync_directory(db: DbSession, connector: DirectoryConnector) -> DirectorySyncRun:
    """Sync one connector's snapshot into Users/Groups/GroupMemberships
    (spec §22-30). Read-only towards the upstream, idempotent, and always
    leaves a DirectorySyncRun behind — FAILED with the error if the
    connector couldn't produce a snapshot, in which case nothing is
    touched (a partial upstream answer must never deactivate anyone).
    """
    source = connector.source
    issuer = f"directory:{source}"
    run = DirectorySyncRun(source=source, status="RUNNING")
    db.add(run)
    db.flush()

    try:
        snapshot = connector.fetch()
    except DirectoryConnectorError as exc:
        run.status = "FAILED"
        run.error = str(exc)[:2000]
        run.finished_at = datetime.now(UTC)
        append_audit_event(
            db, action="DIRECTORY_SYNC_FAILED",
            target_type="directory_sync_run", target_id=str(run.id),
            metadata={"source": source, "error": run.error},
        )
        db.commit()
        return run

    groups_by_external_id: dict[str, Group] = {}
    for entry in snapshot.groups:
        group = db.execute(
            select(Group).where(Group.source == source, Group.external_id == entry.external_id)
        ).scalar_one_or_none()
        if group is None:
            group = Group(source=source, external_id=entry.external_id, name=entry.name)
            db.add(group)
            run.groups_added += 1
        else:
            run.groups_updated += 1
        group.name = entry.name
        group.description = entry.description[:1000]
        group.active = True
        groups_by_external_id[entry.external_id] = group
    db.flush()

    # A group that disappeared upstream is deactivated, not deleted.
    for stale_group in db.execute(select(Group).where(Group.source == source)).scalars():
        if stale_group.external_id not in groups_by_external_id:
            stale_group.active = False
    source_group_ids = set(
        db.execute(select(Group.id).where(Group.source == source)).scalars()
    )

    seen_external_ids: set[str] = set()
    for entry_user in snapshot.users:
        seen_external_ids.add(entry_user.external_id)

        user = db.execute(
            select(User).where(User.issuer == issuer, User.subject == entry_user.external_id)
        ).scalar_one_or_none()
        if user is None:
            # Someone who already logged in via real SSO with this email
            # owns this identity now — sync updates that same row instead
            # of creating a second one for the same person.
            user = db.execute(
                select(User).where(User.email == entry_user.email)
            ).scalar_one_or_none()

        display_name = f"{entry_user.given_name} {entry_user.family_name}".strip()
        if user is None:
            user = User(
                issuer=issuer,
                subject=entry_user.external_id,
                external_directory_id=entry_user.external_id,
                email=entry_user.email,
                given_name=entry_user.given_name,
                family_name=entry_user.family_name,
                display_name=display_name,
                active=entry_user.active,
            )
            db.add(user)
            run.users_added += 1
        else:
            user.external_directory_id = entry_user.external_id
            user.given_name = entry_user.given_name
            user.family_name = entry_user.family_name
            user.display_name = display_name
            user.active = entry_user.active
            run.users_updated += 1
        db.flush()

        # Only this source's memberships are reconciled — another
        # connector's groups are none of our business.
        current_group_ids = set(
            db.execute(
                select(GroupMembership.group_id).where(
                    GroupMembership.user_id == user.id,
                    GroupMembership.group_id.in_(source_group_ids),
                )
            ).scalars()
        )
        desired_group_ids = {
            groups_by_external_id[gid].id
            for gid in entry_user.group_ids
            if gid in groups_by_external_id
        }
        for new_group_id in desired_group_ids - current_group_ids:
            db.add(GroupMembership(group_id=new_group_id, user_id=user.id))
            run.memberships_added += 1
        for stale_group_id in current_group_ids - desired_group_ids:
            db.execute(
                delete(GroupMembership).where(
                    GroupMembership.user_id == user.id, GroupMembership.group_id == stale_group_id
                )
            )
            run.memberships_removed += 1

    # A user previously synced from this source but no longer present
    # upstream is deactivated, never deleted — their signature history
    # must stay intact (spec §30).
    previously_synced = db.execute(select(User).where(User.issuer == issuer)).scalars()
    for user in previously_synced:
        if user.subject not in seen_external_ids and user.active:
            user.active = False
            run.users_deactivated += 1

    run.status = "SUCCESS"
    run.finished_at = datetime.now(UTC)
    append_audit_event(
        db, action="DIRECTORY_SYNC_COMPLETED",
        target_type="directory_sync_run", target_id=str(run.id),
        metadata={
            "source": source,
            "users_added": run.users_added,
            "users_updated": run.users_updated,
            "users_deactivated": run.users_deactivated,
            "groups_added": run.groups_added,
            "groups_updated": run.groups_updated,
            "memberships_added": run.memberships_added,
            "memberships_removed": run.memberships_removed,
        },
    )
    db.commit()
    return run


def sync_local_directory(db: DbSession) -> DirectorySyncRun:
    return sync_directory(db, LocalConnector())
