from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.config import Settings
from lcit_sign.deps import get_db, require_roles, user_roles
from lcit_sign.models.audit import AuditEvent
from lcit_sign.models.signing_key import SigningKey
from lcit_sign.models.user import Role, User, UserRole
from lcit_sign.services.audit import append_audit_event, verify_audit_chain
from lcit_sign.services.signing_keys import get_or_create_active_key, rotate_signing_key

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_roles(Role.ADMIN))]
)


class RoleGrantRequest(BaseModel):
    role: Role


@router.get("/users")
def list_users(db: DbSession = Depends(get_db)) -> list[dict[str, Any]]:
    users = db.execute(select(User).order_by(User.email)).scalars()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "active": u.active,
            "roles": sorted(role.value for role in user_roles(db, u)),
        }
        for u in users
    ]


@router.post("/users/{target_user_id}/roles", status_code=201)
def grant_role(
    target_user_id: uuid.UUID,
    body: RoleGrantRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    target = db.get(User, target_user_id)
    if target is None:
        raise HTTPException(404, "User not found")

    existing = db.execute(
        select(UserRole).where(UserRole.user_id == target.id, UserRole.role == body.role)
    ).scalar_one_or_none()
    if existing is None:
        db.add(UserRole(user_id=target.id, role=body.role))
        append_audit_event(
            db, action="USER_ROLE_CHANGED", actor_id=user.id,
            target_type="user", target_id=str(target.id),
            metadata={"change": "grant", "role": body.role.value},
        )
        db.commit()
    return {"id": str(target.id), "roles": sorted(role.value for role in user_roles(db, target))}


@router.delete("/users/{target_user_id}/roles/{role}", status_code=200)
def revoke_role(
    target_user_id: uuid.UUID,
    role: Role,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    target = db.get(User, target_user_id)
    if target is None:
        raise HTTPException(404, "User not found")

    existing = db.execute(
        select(UserRole).where(UserRole.user_id == target.id, UserRole.role == role)
    ).scalar_one_or_none()
    if existing is not None:
        db.delete(existing)
        append_audit_event(
            db, action="USER_ROLE_CHANGED", actor_id=user.id,
            target_type="user", target_id=str(target.id),
            metadata={"change": "revoke", "role": role.value},
        )
        db.commit()
    return {"id": str(target.id), "roles": sorted(role.value for role in user_roles(db, target))}


@router.get("/audit")
def list_audit_events(
    db: DbSession = Depends(get_db),
    action: str | None = None,
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    stmt = select(AuditEvent).order_by(AuditEvent.sequence.desc())
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    rows = db.execute(stmt.limit(limit).offset(offset)).scalars()
    return [
        {
            "event_id": str(row.event_id),
            "timestamp_utc": row.timestamp_utc.isoformat(),
            "actor_id": str(row.actor_id) if row.actor_id else None,
            "actor_identity_snapshot": row.actor_identity_snapshot,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "result": row.result,
            "request_id": row.request_id,
            "metadata": row.metadata_json,
        }
        for row in rows
    ]


@router.get("/audit/integrity")
def check_audit_integrity(db: DbSession = Depends(get_db)) -> dict[str, Any]:
    is_valid, first_bad_sequence = verify_audit_chain(db)
    return {"valid": is_valid, "first_invalid_sequence": first_bad_sequence}


def _signing_key_payload(key: SigningKey) -> dict[str, Any]:
    return {
        "key_id": key.key_id,
        "public_key_hex": key.public_key_hex,
        "status": key.status.value,
        "created_at": key.created_at.isoformat(),
        "activated_at": key.activated_at.isoformat() if key.activated_at else None,
        "retired_at": key.retired_at.isoformat() if key.retired_at else None,
    }


@router.get("/signing-keys")
def list_signing_keys(db: DbSession = Depends(get_db)) -> list[dict[str, Any]]:
    keys = db.execute(select(SigningKey).order_by(SigningKey.created_at.desc())).scalars()
    return [_signing_key_payload(k) for k in keys]


@router.post("/signing-keys/rotate", status_code=201)
def rotate_signing_keys(
    request: Request,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    if not settings.master_key:
        raise HTTPException(503, "LCIT_SIGN_MASTER_KEY is not configured")
    # Ensures a key exists at all before "rotating" it on a brand-new install.
    get_or_create_active_key(db, settings.master_key)
    new_key = rotate_signing_key(db, settings.master_key, actor_id=user.id)
    db.commit()
    return _signing_key_payload(new_key)
