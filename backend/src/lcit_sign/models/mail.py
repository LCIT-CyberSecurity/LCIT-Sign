from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from lcit_sign.database import Base


class NotificationType(enum.StrEnum):
    DOCUMENT_TO_SIGN = "DOCUMENT_TO_SIGN"
    REMINDER = "REMINDER"
    SIGNATURE_CONFIRMATION = "SIGNATURE_CONFIRMATION"
    TEST_EMAIL = "TEST_EMAIL"


class NotificationStatus(enum.StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"
    RETRY = "RETRY"


class MailConnector(Base):
    """SMTP configuration — a single row (id=1), like the audit chain
    state. The password is stored only as `encrypted_password`, AES-GCM
    ciphertext under the runtime master key (spec §99-101); the API never
    returns it, encrypted or not.
    """

    __tablename__ = "mail_connectors"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    # "smtp" (generic relay) or "graph" (Microsoft Graph, one dedicated
    # mailbox = from_address; the client secret lives in encrypted_password).
    kind: Mapped[str] = mapped_column(String(10), default="smtp")
    graph_tenant_id: Mapped[str | None] = mapped_column(String(100))
    graph_client_id: Mapped[str | None] = mapped_column(String(100))
    host: Mapped[str] = mapped_column(String(255), default="")
    port: Mapped[int] = mapped_column(Integer, default=587)
    use_tls: Mapped[bool] = mapped_column(Boolean, default=False)
    use_starttls: Mapped[bool] = mapped_column(Boolean, default=True)
    username: Mapped[str] = mapped_column(String(255), default="")
    encrypted_password: Mapped[str | None] = mapped_column(String(1000))
    from_address: Mapped[str] = mapped_column(String(320))
    reply_to: Mapped[str | None] = mapped_column(String(320))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Notification(Base):
    """A queued outbound email (spec §73-74). Created inside the same
    transaction as the business event it reports, but never sent inline —
    the background worker (services.notification_worker) is the only
    thing that calls SMTP, so an SMTP outage never rolls back a signature.
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, native_enum=False, length=32)
    )
    recipient_email: Mapped[str] = mapped_column(String(320))
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    subject: Mapped[str] = mapped_column(String(255))
    body_text: Mapped[str] = mapped_column(String(10000))
    related_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signature_assignments.id")
    )

    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, native_enum=False, length=20), default=NotificationStatus.PENDING
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(1000))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
