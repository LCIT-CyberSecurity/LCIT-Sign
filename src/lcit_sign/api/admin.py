from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.config import Settings
from lcit_sign.deps import get_db, require_roles, user_roles
from lcit_sign.models.audit import AuditEvent
from lcit_sign.models.mail import MailConnector, Notification, NotificationStatus, NotificationType
from lcit_sign.models.signing_key import SigningKey, SigningKeyStatus
from lcit_sign.models.user import Role, User, UserRole
from lcit_sign.services.audit import append_audit_event, verify_audit_chain
from lcit_sign.services.crypto import decrypt_secret, encrypt_secret
from lcit_sign.services.mail import (
    MailSendError,
    build_sender,
)
from lcit_sign.services.mail_graph import GraphSender
from lcit_sign.services.signing_keys import get_or_create_active_key, rotate_signing_key
from lcit_sign.services.ssrf import OutboundTargetError, validate_outbound_target

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
            "campaign_id": str(row.campaign_id) if row.campaign_id else None,
            "document_id": str(row.document_id) if row.document_id else None,
            "signature_id": str(row.signature_id) if row.signature_id else None,
            "request_id": row.request_id,
            "source_ip": row.source_ip,
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
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
    }


@router.get("/signing-keys")
def list_signing_keys(db: DbSession = Depends(get_db)) -> list[dict[str, Any]]:
    keys = db.execute(select(SigningKey).order_by(SigningKey.created_at.desc())).scalars()
    return [_signing_key_payload(k) for k in keys]


@router.post("/signing-keys/{key_id}/revoke")
def revoke_signing_key(
    key_id: str,
    request: Request,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Withdraw trust from a key (spec §43 REVOKED), e.g. after a suspected
    compromise. Signatures it made then fail verification's
    `signing_key_trusted` check. Revoking the ACTIVE key first rotates, so the
    platform is never left without a key to sign with."""
    settings: Settings = request.app.state.settings
    key = db.execute(select(SigningKey).where(SigningKey.key_id == key_id)).scalar_one_or_none()
    if key is None:
        raise HTTPException(404, "Signing key not found")
    if key.status == SigningKeyStatus.REVOKED:
        raise HTTPException(409, "Key is already revoked")
    if key.status == SigningKeyStatus.ACTIVE:
        if not settings.master_key:
            raise HTTPException(503, "LCIT_SIGN_MASTER_KEY is not configured")
        rotate_signing_key(db, settings.master_key, actor_id=user.id)
    key.status = SigningKeyStatus.REVOKED
    key.revoked_at = datetime.now(UTC)
    append_audit_event(
        db, action="SIGNING_KEY_REVOKED", actor_id=user.id,
        target_type="signing_key", target_id=key.key_id,
    )
    db.commit()
    return _signing_key_payload(key)


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


def _check_mail_target(host: str, port: int) -> None:
    try:
        validate_outbound_target(host, port)
    except OutboundTargetError as exc:
        raise HTTPException(422, f"SMTP target rejected: {exc}") from exc


def get_mail_http_client() -> Generator[httpx.Client]:
    # A dependency so tests can swap in a mock transport.
    with httpx.Client(timeout=15.0) as client:
        yield client


class MailConnectorRequest(BaseModel):
    kind: Literal["smtp", "graph"] = "smtp"
    # Microsoft Graph: the dedicated mailbox is `from_address`; the client
    # secret goes in `password` and is stored encrypted like an SMTP one.
    graph_tenant_id: str | None = None
    graph_client_id: str | None = None
    host: str = ""
    port: int = 587
    use_tls: bool = False
    use_starttls: bool = True
    username: str = ""
    password: str | None = None  # omitted/None keeps the existing encrypted value
    from_address: str
    reply_to: str | None = None
    timeout_seconds: int = 10

    @model_validator(mode="after")
    def _kind_requirements(self) -> MailConnectorRequest:
        if self.kind == "smtp" and not self.host:
            raise ValueError("host is required for an SMTP connector")
        if self.kind == "graph" and not (self.graph_tenant_id and self.graph_client_id):
            raise ValueError("graph_tenant_id and graph_client_id are required for Graph")
        return self


def _mail_connector_payload(connector: MailConnector) -> dict[str, Any]:
    return {
        "kind": connector.kind,
        "graph_tenant_id": connector.graph_tenant_id,
        "graph_client_id": connector.graph_client_id,
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
    if body.kind == "smtp":
        _check_mail_target(body.host, body.port)
    settings: Settings = request.app.state.settings
    connector = db.get(MailConnector, 1)
    if connector is None:
        connector = MailConnector(id=1, from_address=body.from_address)
        db.add(connector)

    connector.kind = body.kind
    connector.graph_tenant_id = body.graph_tenant_id if body.kind == "graph" else None
    connector.graph_client_id = body.graph_client_id if body.kind == "graph" else None

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


def _stored_secret(connector: MailConnector, settings: Settings) -> str | None:
    if connector.encrypted_password and settings.master_key:
        return decrypt_secret(settings.master_key, connector.encrypted_password)
    return None


@router.post("/mail-connector/test-connection")
def test_mail_connection(
    request: Request,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
    http_client: httpx.Client = Depends(get_mail_http_client),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    connector = db.get(MailConnector, 1)
    if connector is None:
        raise HTTPException(404, "Mail connector is not configured")
    if connector.kind == "smtp":
        _check_mail_target(connector.host, connector.port)

    results = build_sender(connector, _stored_secret(connector, settings), http_client).diagnose()

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
    http_client: httpx.Client = Depends(get_mail_http_client),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    connector = db.get(MailConnector, 1)
    if connector is None:
        raise HTTPException(404, "Mail connector is not configured")
    if connector.kind == "smtp":
        _check_mail_target(connector.host, connector.port)
    sender = build_sender(connector, _stored_secret(connector, settings), http_client)

    try:
        sender.send(
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


class IsolationTestRequest(BaseModel):
    other_mailbox: str
    to: str


@router.post("/mail-connector/test-isolation")
def test_mail_isolation(
    request: Request,
    body: IsolationTestRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
    http_client: httpx.Client = Depends(get_mail_http_client),
) -> dict[str, Any]:
    """Negative test required before trusting a Graph connector (spec §63
    step 9): the application must NOT be able to send as another mailbox.
    Sends nothing when the tenant is correctly confined."""
    settings: Settings = request.app.state.settings
    connector = db.get(MailConnector, 1)
    if connector is None or connector.kind != "graph":
        raise HTTPException(409, "Only a Microsoft Graph connector can be isolation-tested")
    sender = build_sender(connector, _stored_secret(connector, settings), http_client)
    assert isinstance(sender, GraphSender)  # noqa: S101
    try:
        isolated = sender.test_isolation(body.other_mailbox, body.to)
    except MailSendError as exc:
        raise HTTPException(422, str(exc)) from exc
    append_audit_event(
        db, action="MAIL_TEST_EXECUTED", actor_id=user.id,
        result="SUCCESS" if isolated else "FAILURE",
        target_type="mail_connector", target_id="1",
        metadata={"test": "isolation", "isolated": isolated},
    )
    db.commit()
    return {
        "isolated": isolated,
        "detail": "Mail.Send is confined to the dedicated mailbox."
        if isolated
        else "WARNING: the application could send as another mailbox. "
        "Restrict it with Exchange Online Application RBAC before using it.",
    }
