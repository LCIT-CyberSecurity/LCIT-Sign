from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lcit_sign.database import Base


class CampaignStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    ARCHIVED = "ARCHIVED"


class CampaignTargetMode(enum.StrEnum):
    ALL_USERS = "ALL_USERS"
    # Group-based targeting (spec §33) is added once Phase 6's Group model
    # exists; SPECIFIC_USERS already covers "one or more users".
    SPECIFIC_USERS = "SPECIFIC_USERS"


class AssignmentStatus(enum.StrEnum):
    PENDING = "PENDING"
    VIEWED = "VIEWED"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class Campaign(Base):
    """A signature campaign (spec §44-47). The workflow is intentionally
    flat — independent, parallel signatures, no stages/approvals — per the
    spec's explicit "don't build a BPM engine" instruction.
    """

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(2000), default="")
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, native_enum=False, length=20), default=CampaignStatus.DRAFT
    )
    target_mode: Mapped[CampaignTargetMode] = mapped_column(
        Enum(CampaignTargetMode, native_enum=False, length=20),
        default=CampaignTargetMode.SPECIFIC_USERS,
    )

    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    launch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    documents: Mapped[list[CampaignDocument]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class CampaignDocument(Base):
    """One document version a campaign asks its targets to sign. Pinned to
    a specific version at add-time — never "the current published one" —
    so a later republish never silently changes what an active campaign
    means (spec §34 snapshot philosophy, applied to content too).
    """

    __tablename__ = "campaign_documents"

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"), primary_key=True)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"), primary_key=True
    )

    campaign: Mapped[Campaign] = relationship(back_populates="documents")


class CampaignTargetUser(Base):
    """An explicitly-targeted user, used when target_mode is
    SPECIFIC_USERS (or as the "additional users" on top of a future
    group-based mode)."""

    __tablename__ = "campaign_target_users"

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)


class SignatureAssignment(Base):
    """One user's individual obligation to sign one document version within
    one campaign (spec §48). Created once, at launch, from the campaign's
    frozen population snapshot — never recomputed later from live group
    membership (spec §34).
    """

    __tablename__ = "signature_assignments"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "document_version_id", "user_id", name="uq_assignment_campaign_doc_user"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"))
    document_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus, native_enum=False, length=20), default=AssignmentStatus.PENDING
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    first_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signature_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("signatures.id"))

    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
