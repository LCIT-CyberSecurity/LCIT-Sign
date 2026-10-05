from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.deps import get_db, require_roles
from lcit_sign.models.directory import DirectorySyncRun, Group, GroupMembership
from lcit_sign.models.user import Role, User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.directory_sync import SOURCE, sync_local_directory

router = APIRouter(prefix="/admin/directory", tags=["directory"])

_admin = require_roles(Role.ADMIN)
# Reading the roster is also an OPERATOR need (picking groups to target a
# campaign at, spec §33); only mutating the directory (sync) stays
# ADMIN-only, matching spec §12-13's split of responsibilities.
_read = require_roles(Role.OPERATOR, Role.ADMIN)


def _run_payload(run: DirectorySyncRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "source": run.source,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "users_added": run.users_added,
        "users_updated": run.users_updated,
        "users_deactivated": run.users_deactivated,
        "groups_added": run.groups_added,
        "groups_updated": run.groups_updated,
        "memberships_added": run.memberships_added,
        "memberships_removed": run.memberships_removed,
        "error": run.error,
    }


@router.post("/sync")
def trigger_sync(db: DbSession = Depends(get_db), user: User = Depends(_admin)) -> dict[str, Any]:
    append_audit_event(
        db, action="DIRECTORY_SYNC_STARTED", actor_id=user.id, metadata={"source": SOURCE}
    )
    db.commit()
    run = sync_local_directory(db)
    return _run_payload(run)


@router.get("/sync-runs")
def list_sync_runs(
    db: DbSession = Depends(get_db), user: User = Depends(_admin)
) -> list[dict[str, Any]]:
    stmt = select(DirectorySyncRun).order_by(DirectorySyncRun.started_at.desc())
    runs = db.execute(stmt).scalars()
    return [_run_payload(r) for r in runs]


@router.get("/groups")
def list_groups(
    db: DbSession = Depends(get_db), user: User = Depends(_read)
) -> list[dict[str, Any]]:
    counts = dict(
        db.execute(
            select(GroupMembership.group_id, func.count()).group_by(GroupMembership.group_id)
        ).all()
    )
    groups = db.execute(select(Group).order_by(Group.name)).scalars()
    return [
        {
            "id": str(g.id),
            "source": g.source,
            "name": g.name,
            "description": g.description,
            "active": g.active,
            "member_count": counts.get(g.id, 0),
        }
        for g in groups
    ]


@router.get("/groups/{group_id}/members")
def list_group_members(
    group_id: uuid.UUID, db: DbSession = Depends(get_db), user: User = Depends(_read)
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(User)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .where(GroupMembership.group_id == group_id)
        .order_by(User.email)
    ).scalars()
    return [
        {"id": str(u.id), "email": u.email, "display_name": u.display_name, "active": u.active}
        for u in rows
    ]
