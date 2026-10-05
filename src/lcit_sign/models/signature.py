from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from lcit_sign.database import Base


class Signature(Base):
    """A completed, immutable signature act (spec §59-61).

    Carries both the operational fact (who signed what, when) and the
    evidence snapshot (identity and consent as they were *at signing
    time* — a later change to the user's email or the consent text must
    never alter this row, spec §21/§51/§61). The rendered PDF, the
    evidence.json export and the human-readable certificate PDF are
    generated once at signing time and stored under this row's own id in
    the "signed", "evidence" and "certificates" storage buckets.
    """

    __tablename__ = "signatures"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "document_version_id",
            "campaign_id",
            name="uq_signature_user_version_campaign",
        ),
        Index(
            "uq_signature_user_version_no_campaign",
            "user_id",
            "document_version_id",
            unique=True,
            postgresql_where=text("campaign_id IS NULL"),
            sqlite_where=text("campaign_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    campaign_id: Mapped[uuid.UUID | None]
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    document_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    # Identity snapshot, frozen at signing time (spec §61).
    identity_provider: Mapped[str] = mapped_column(String(255))
    issuer: Mapped[str] = mapped_column(String(512))
    subject: Mapped[str] = mapped_column(String(255))
    email_snapshot: Mapped[str] = mapped_column(String(320))
    display_name_snapshot: Mapped[str] = mapped_column(String(255))

    consent_text: Mapped[str] = mapped_column(String(1000))
    consent_version: Mapped[str] = mapped_column(String(50))

    signed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    original_file_sha256: Mapped[str] = mapped_column(String(64))
    signed_file_sha256: Mapped[str] = mapped_column(String(64))

    application_version: Mapped[str] = mapped_column(String(50))
    signing_key_id: Mapped[str] = mapped_column(String(64))
    evidence_hash: Mapped[str] = mapped_column(String(64))
    cryptographic_signature: Mapped[str] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def display_id(self) -> str:
        # A human-readable reference (spec §58's "SIG-..." example),
        # derived from the id itself rather than a separate counter —
        # avoids a contended global sequence for no real MVP benefit.
        return f"SIG-{self.id.hex[:12].upper()}"
