from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.deps import get_db, require_roles
from lcit_sign.models.audit import AuditEvent
from lcit_sign.models.user import Role
from lcit_sign.services.audit import verify_audit_chain

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_roles(Role.ADMIN))]
)


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
