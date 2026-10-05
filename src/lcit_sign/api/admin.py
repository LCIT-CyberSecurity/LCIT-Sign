from __future__ import annotations

import re
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, model_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session as DbSession

from lcit_sign.api.directory import check_connector_input
from lcit_sign.config import Settings
from lcit_sign.deps import get_db, require_roles, user_roles
from lcit_sign.models.audit import AuditEvent
from lcit_sign.models.campaign import Campaign, SignatureAssignment
from lcit_sign.models.directory import GroupMembership
from lcit_sign.models.document import Document
from lcit_sign.models.mail import MailConnector, Notification, NotificationStatus, NotificationType
from lcit_sign.models.report import Report
from lcit_sign.models.session import Session as SessionRecord
from lcit_sign.models.signature import Signature
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


def user_source(user: User) -> str:
    """Where this person comes from, for display: a directory (entra, google,
    ldap, local demo), 'manual' (added by an administrator), 'builtin' (the
    local administrator account) or 'sso' (they simply signed in)."""
    if user.issuer.startswith("directory:"):
        return user.issuer.split(":", 1)[1]
    if user.issuer.startswith("builtin:"):
        return "builtin"
    return "sso"


def _user_blockers(db: DbSession, users: list[User]) -> dict[uuid.UUID, list[str]]:
    """Why each user cannot be erased. Someone who has signed, was asked to sign,
    or authored documents/campaigns/reports is part of the evidence trail —
    they can only be disabled. People kept in step with an external directory
    would simply come back at the next sync."""
    ids = [u.id for u in users]
    blockers: dict[uuid.UUID, list[str]] = {uid: [] for uid in ids}
    if not ids:
        return blockers

    def count(model_column: Any, label: str) -> None:
        for uid, n in db.execute(
            select(model_column, func.count()).where(model_column.in_(ids)).group_by(model_column)
        ).all():
            blockers[uid].append(f"{n} {label}")

    count(Signature.user_id, "signature(s)")
    count(SignatureAssignment.user_id, "document(s) à signer")
    count(Document.created_by, "document(s) créé(s)")
    count(Campaign.created_by, "campagne(s) créée(s)")
    count(Report.generated_by, "procès-verbal(aux) généré(s)")
    for user in users:
        source = user_source(user)
        if source not in ("sso", "manual"):
            blockers[user.id].append(f"géré par la source « {source} »")
    return blockers


def _admin_count(db: DbSession) -> int:
    return db.execute(
        select(func.count())
        .select_from(UserRole)
        .join(User, User.id == UserRole.user_id)
        .where(UserRole.role == Role.ADMIN, User.active.is_(True))
    ).scalar_one()


def _user_payload(
    db: DbSession, u: User, blockers: dict[uuid.UUID, list[str]]
) -> dict[str, Any]:
    return {
        "id": str(u.id),
        "email": u.email,
        "display_name": u.display_name,
        "active": u.active,
        "manually_disabled": u.manually_disabled,
        "source": user_source(u),
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "roles": sorted(role.value for role in user_roles(db, u)),
        "can_delete": not blockers.get(u.id),
        "delete_blockers": blockers.get(u.id, []),
    }


@router.get("/users")
def list_users(db: DbSession = Depends(get_db)) -> list[dict[str, Any]]:
    users = list(db.execute(select(User).order_by(User.email)).scalars())
    blockers = _user_blockers(db, users)
    return [_user_payload(db, u, blockers) for u in users]


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CreateUserRequest(BaseModel):
    email: str
    given_name: str = ""
    family_name: str = ""
    roles: list[Role] = [Role.SIGNER]


@router.post("/users", status_code=201)
def create_user(
    body: CreateUserRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Add someone by e-mail address, with no password and no account anywhere:
    they sign in with their usual SSO and are matched to this entry by address,
    keeping the roles given here."""
    email = body.email.strip().lower()
    if not _EMAIL.match(email) or len(email) > 320:
        raise HTTPException(422, "Adresse e-mail invalide")
    clash = db.execute(select(User.id).where(func.lower(User.email) == email)).first()
    if clash is not None:
        raise HTTPException(409, "Un utilisateur avec cette adresse existe déjà")

    given, family = body.given_name.strip(), body.family_name.strip()
    created = User(
        issuer="directory:manual",
        subject=f"manual:{uuid.uuid4()}",
        email=email,
        given_name=given,
        family_name=family,
        display_name=f"{given} {family}".strip() or email.split("@")[0],
        active=True,
    )
    db.add(created)
    db.flush()
    for role in set(body.roles):
        db.add(UserRole(user_id=created.id, role=role))
    append_audit_event(
        db, action="USER_CREATED", actor_id=user.id, target_type="user",
        target_id=str(created.id), metadata={"email": email, "source": "manual"},
    )
    db.commit()
    return _user_payload(db, created, _user_blockers(db, [created]))


class UpdateUserRequest(BaseModel):
    active: bool


@router.patch("/users/{target_user_id}")
def update_user(
    target_user_id: uuid.UUID,
    body: UpdateUserRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Disable or re-enable someone. Disabling ends their sessions at once, keeps
    all their history, and survives directory syncs."""
    target = db.get(User, target_user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if not body.active:
        if target.id == user.id:
            raise HTTPException(409, "Vous ne pouvez pas désactiver votre propre compte")
        is_admin = Role.ADMIN in user_roles(db, target)
        if is_admin and target.active and _admin_count(db) <= 1:
            raise HTTPException(
                409, "C'est le dernier administrateur actif : il ne peut pas être désactivé"
            )
    target.active = body.active
    target.manually_disabled = not body.active
    if not body.active:
        for session in db.execute(
            select(SessionRecord).where(
                SessionRecord.user_id == target.id, SessionRecord.revoked_at.is_(None)
            )
        ).scalars():
            session.revoked_at = datetime.now(UTC)
    append_audit_event(
        db, action="USER_UPDATED", actor_id=user.id, target_type="user",
        target_id=str(target.id), metadata={"active": body.active},
    )
    db.commit()
    return _user_payload(db, target, _user_blockers(db, [target]))


@router.delete("/users/{target_user_id}")
def delete_user(
    target_user_id: uuid.UUID,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Erase someone who left no trace (never signed, never asked, authored
    nothing). Anyone else is refused with the reason: disable them instead."""
    target = db.get(User, target_user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if target.id == user.id:
        raise HTTPException(409, "Vous ne pouvez pas supprimer votre propre compte")
    reasons = _user_blockers(db, [target])[target.id]
    if reasons:
        raise HTTPException(
            409,
            "Cet utilisateur ne peut pas être supprimé (" + " ; ".join(reasons) + "). "
            "Désactivez-le à la place.",
        )
    if Role.ADMIN in user_roles(db, target) and target.active and _admin_count(db) <= 1:
        raise HTTPException(409, "C'est le dernier administrateur actif")
    email = target.email
    db.execute(delete(UserRole).where(UserRole.user_id == target.id))
    db.execute(delete(GroupMembership).where(GroupMembership.user_id == target.id))
    db.execute(delete(SessionRecord).where(SessionRecord.user_id == target.id))
    db.execute(
        update(Notification)
        .where(Notification.recipient_user_id == target.id)
        .values(recipient_user_id=None)
    )
    db.delete(target)
    append_audit_event(
        db, action="USER_DELETED", actor_id=user.id, target_type="user",
        target_id=str(target_user_id), metadata={"email": email},
    )
    db.commit()
    return {"deleted": str(target_user_id)}


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
    else:
        check_connector_input(
            "entra",
            {
                "tenant_id": body.graph_tenant_id or "",
                "client_id": body.graph_client_id or "",
            },
            body.password,
        )
        if "@" not in body.from_address:
            raise HTTPException(422, "L'expéditeur doit être une adresse e-mail complète.")
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
