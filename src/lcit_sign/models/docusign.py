from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from lcit_sign.database import Base


class DocusignConfig(Base):
    """The DocuSign connection — a single row (id=1). The private key is stored only as
    `encrypted_private_key`, AES-GCM ciphertext under the runtime master key, and never
    returned by the API. `environment` is "demo" (DocuSign's developer sandbox),
    "production", or "test" (the mock DocuSign of the test stack, addresses in `auth_url` /
    `api_url`)."""

    __tablename__ = "docusign_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    environment: Mapped[str] = mapped_column(String(20), default="demo")
    integration_key: Mapped[str] = mapped_column(String(100), default="")
    user_id: Mapped[str] = mapped_column(String(100), default="")
    account_id: Mapped[str] = mapped_column(String(100), default="")
    auth_url: Mapped[str | None] = mapped_column(String(500))
    api_url: Mapped[str | None] = mapped_column(String(500))
    encrypted_private_key: Mapped[str | None] = mapped_column(String(10000))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class DocusignEnvelope(Base):
    """The DocuSign envelope that answers one assignment: queued when the person's turn
    comes, sent and followed by the worker, completed when DocuSign says everyone signed.
    QUEUED → SENT → COMPLETED, or DECLINED / VOIDED / FAILED."""

    __tablename__ = "docusign_envelopes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signature_assignments.id"), unique=True
    )
    envelope_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    error: Mapped[str | None] = mapped_column(String(1000))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
