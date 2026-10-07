from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, func
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
    description: Mapped[str] = mapped_column(String(2000), default="")
    category: Mapped[str] = mapped_column(String(100), default="")
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
    # A document uploaded as Word / LibreOffice: the hash of that source file, which is kept
    # next to the PDF made from it (the PDF is what gets signed; `sha256` is its hash).
    source_sha256: Mapped[str | None] = mapped_column(String(64))

    status: Mapped[DocumentVersionStatus] = mapped_column(
        Enum(DocumentVersionStatus, native_enum=False, length=20),
        default=DocumentVersionStatus.DRAFT,
    )
    # Names given to the signer roles in the editor ({"1": "RSSI", "2": "Collaborateur"}).
    # Roles stay generic — a name says what the role is, never who it is; the people
    # are chosen when a campaign is launched. Frozen with the version.
    role_labels: Mapped[dict[str, str] | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="versions")


class FieldKind(enum.StrEnum):
    """What an element placed on a document is (a signature, a date…)."""

    SIGNATURE = "SIGNATURE"   # the signer's name, handwritten-style — automatic
    DATE = "DATE"             # today's date, at signing — automatic
    TIME = "TIME"             # the time, at signing — automatic
    FULL_NAME = "FULL_NAME"   # first and last name — automatic
    FIRST_NAME = "FIRST_NAME"  # first name — automatic
    LAST_NAME = "LAST_NAME"   # last name — automatic
    EMAIL = "EMAIL"           # the signer's address — automatic
    TEXT = "TEXT"             # free text typed by the signer
    PLACE = "PLACE"           # a place, typed by the signer ("Fait à ...")
    LOGO = "LOGO"             # the company logo — automatic


# Filled in by the platform from the authenticated identity: nothing to type.
AUTOMATIC_KINDS = frozenset(
    {
        FieldKind.SIGNATURE,
        FieldKind.DATE,
        FieldKind.TIME,
        FieldKind.FULL_NAME,
        FieldKind.FIRST_NAME,
        FieldKind.LAST_NAME,
        FieldKind.EMAIL,
        FieldKind.LOGO,
    }
)
# Typed by the signer.
INPUT_KINDS = frozenset({FieldKind.TEXT, FieldKind.PLACE})


class DocumentField(Base):
    """One element the operator placed on a page of a document version.

    Geometry is stored as fractions of the page (0..1, origin top-left), so it
    does not depend on the resolution the editor happened to render at. The
    set is editable while the version is a draft and frozen with publication,
    like the file itself.
    """

    __tablename__ = "document_fields"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"), index=True
    )
    page: Mapped[int] = mapped_column(Integer)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    kind: Mapped[FieldKind] = mapped_column(Enum(FieldKind, native_enum=False, length=20))
    label: Mapped[str] = mapped_column(String(120), default="")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    # Which signer fills it (1 = first). One role until multi-signer routing.
    role: Mapped[int] = mapped_column(Integer, default=1)
    # Fields sharing a group key are filled once and apply everywhere.
    group_key: Mapped[str | None] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer, default=0)
