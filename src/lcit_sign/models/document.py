from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lcit_sign.database import Base


class DocumentVersionStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class Document(Base):
    """The logical document (e.g. "Charte informatique"). All actual
    content lives on its DocumentVersion rows — spec §36-38.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", order_by="DocumentVersion.created_at"
    )


class DocumentVersion(Base):
    """One immutable-once-published rendition of a Document (spec §37-38).

    `stored_filename` is always the version's own `id` — the original
    upload's filename is kept only as display metadata and must never be
    used to build a filesystem path (spec §9, §40, §107).
    """

    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    version_label: Mapped[str] = mapped_column(String(50))

    original_filename: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))

    status: Mapped[DocumentVersionStatus] = mapped_column(
        Enum(DocumentVersionStatus, native_enum=False, length=20),
        default=DocumentVersionStatus.DRAFT,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="versions")
