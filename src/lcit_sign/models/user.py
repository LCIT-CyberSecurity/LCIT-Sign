from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lcit_sign.database import Base


class Role(enum.StrEnum):
    """What someone may do besides signing what they were asked to sign (which needs no role).

    SIGNER      sign a published document of one's own accord.
    PREPARER    prepare documents and run signature campaigns — one's own, or those one is
                a preparer of.
    OPERATOR    business administrator: sees every campaign and who owns it, reassigns owners
                and preparers, helps unblock one. Does NOT read the confidential content (the
                documents, the signed PDFs, the proofs) unless made a preparer of the campaign.
    ADMIN       technical administration, and full access.
    """

    SIGNER = "SIGNER"
    PREPARER = "PREPARER"
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"


class User(Base):
    """A person authenticated through SSO.

    Identity is (issuer, subject) — the only part of a user's record that
    never changes. Email and name are mutable attributes synced from the
    identity provider / directory, never a key: see spec §20-21.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    issuer: Mapped[str] = mapped_column(String(512))
    subject: Mapped[str] = mapped_column(String(255))
    external_directory_id: Mapped[str | None] = mapped_column(String(255))
    # Only the built-in system account has one (scrypt hash). Everyone else
    # signs in through SSO and has no password in this application.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # The built-in account starts with an initial password and must change it.
    must_change_password: Mapped[bool] = mapped_column(default=False)

    email: Mapped[str] = mapped_column(String(320))
    given_name: Mapped[str] = mapped_column(String(255), default="")
    family_name: Mapped[str] = mapped_column(String(255), default="")
    display_name: Mapped[str] = mapped_column(String(255), default="")

    active: Mapped[bool] = mapped_column(default=True)
    # Someone from outside the company, added by e-mail address to sign: they sign in with their
    # own account (an Entra guest, a Google account…), and are never touched by a directory sync.
    external: Mapped[bool] = mapped_column(default=False, server_default="0")
    # An administrator switched this person off: a directory sync must not
    # switch them back on just because the directory still lists them.
    manually_disabled: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="roles")
