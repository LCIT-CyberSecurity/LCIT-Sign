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
from lcit_sign.models.mail import MailConnector, Notification, NotificationStatus, NotificationType
from lcit_sign.models.signing_key import SigningKey
from lcit_sign.models.user import Role, User, UserRole
from lcit_sign.services.audit import append_audit_event, verify_audit_chain
from lcit_sign.services.crypto import decrypt_secret, encrypt_secret
from lcit_sign.services.mail import (
    MailSendError,
    credentials_from_connector,
    diagnose_connection,
    send_email,
)
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


class MailConnectorRequest(BaseModel):
    host: str
    port: int = 587
    use_tls: bool = False
    use_starttls: bool = True
    username: str = ""
    password: str | None = None  # omitted/None keeps the existing encrypted value
    from_address: str
    reply_to: str | None = None
    timeout_seconds: int = 10


def _mail_connector_payload(connector: MailConnector) -> dict[str, Any]:
    return {
        "host": connector.host,
        "port": connector.port,
        "use_tls": connector.use_tls,
        "use_starttls": connector.use_starttls,
        "username": connector.username,
        "password_configured": bool(connector.encrypted_password),
        "from_address": connector.from_address,
        "reply_to": connector.reply_to,
        "timeout_seconds": connector.timeout_seconds,
        "updated_at": connector.updated_at.isoformat(),
    }


@router.get("/mail-connector")
def get_mail_connector(db: DbSession = Depends(get_db)) -> dict[str, Any] | None:
    connector = db.get(MailConnector, 1)
    return _mail_connector_payload(connector) if connector else None


@router.put("/mail-connector")
def put_mail_connector(
    request: Request,
    body: MailConnectorRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    connector = db.get(MailConnector, 1)
    if connector is None:
        connector = MailConnector(id=1, from_address=body.from_address)
        db.add(connector)

    connector.host = body.host
    connector.port = body.port
    connector.use_tls = body.use_tls
    connector.use_starttls = body.use_starttls
    connector.username = body.username
    connector.from_address = body.from_address
    connector.reply_to = body.reply_to
    connector.timeout_seconds = body.timeout_seconds
    connector.updated_by = user.id
    if body.password:
        if not settings.master_key:
            raise HTTPException(503, "LCIT_SIGN_MASTER_KEY is not configured")
        connector.encrypted_password = encrypt_secret(settings.master_key, body.password)

    append_audit_event(
        db, action="MAIL_CONFIGURATION_CHANGED", actor_id=user.id,
        target_type="mail_connector", target_id="1",
    )
    db.commit()
    return _mail_connector_payload(connector)


@router.post("/mail-connector/test-connection")
def test_mail_connection(
    request: Request,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    connector = db.get(MailConnector, 1)
    if connector is None:
        raise HTTPException(404, "Mail connector is not configured")

    password = None
    if connector.encrypted_password and settings.master_key:
        password = decrypt_secret(settings.master_key, connector.encrypted_password)
    creds = credentials_from_connector(connector, password)
    results = diagnose_connection(creds)

    append_audit_event(
        db, action="MAIL_TEST_EXECUTED", actor_id=user.id,
        target_type="mail_connector", target_id="1", metadata=results,
    )
    db.commit()
    return results


class SendTestEmailRequest(BaseModel):
    to: str


@router.post("/mail-connector/send-test")
def send_test_email(
    request: Request,
    body: SendTestEmailRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    connector = db.get(MailConnector, 1)
    if connector is None:
        raise HTTPException(404, "Mail connector is not configured")

    password = None
    if connector.encrypted_password and settings.master_key:
        password = decrypt_secret(settings.master_key, connector.encrypted_password)
    creds = credentials_from_connector(connector, password)

    try:
        send_email(
            creds,
            from_address=connector.from_address,
            reply_to=connector.reply_to,
            to=body.to,
            subject="LCIT Sign — e-mail de test",
            body="Ceci est un e-mail de test envoyé depuis LCIT Sign.",
        )
    except MailSendError as exc:
        append_audit_event(
            db, action="MAIL_TEST_EXECUTED", actor_id=user.id, result="FAILURE",
            target_type="mail_connector", target_id="1", metadata={"error": str(exc)},
        )
        db.commit()
        raise HTTPException(502, f"Failed to send test email: {exc}") from exc

    append_audit_event(
        db, action="MAIL_TEST_EXECUTED", actor_id=user.id,
        target_type="mail_connector", target_id="1", metadata={"sent_to": body.to},
    )
    db.commit()
    return {"sent": True}


@router.get("/notifications")
def list_notifications(
    db: DbSession = Depends(get_db),
    status: NotificationStatus | None = None,
    notification_type: NotificationType | None = None,
    limit: int = Query(default=50, le=500),
) -> list[dict[str, Any]]:
    stmt = select(Notification).order_by(Notification.created_at.desc())
    if status is not None:
        stmt = stmt.where(Notification.status == status)
    if notification_type is not None:
        stmt = stmt.where(Notification.notification_type == notification_type)
    rows = db.execute(stmt.limit(limit)).scalars()
    return [
        {
            "id": str(n.id),
            "notification_type": n.notification_type.value,
            "recipient_email": n.recipient_email,
            "subject": n.subject,
            "status": n.status.value,
            "attempt_count": n.attempt_count,
            "last_error": n.last_error,
            "created_at": n.created_at.isoformat(),
            "sent_at": n.sent_at.isoformat() if n.sent_at else None,
        }
        for n in rows
    ]
