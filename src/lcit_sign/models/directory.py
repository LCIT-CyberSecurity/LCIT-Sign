from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from lcit_sign.database import Base


class Group(Base):
    """A directory group, synced read-only from a connector (spec §31).

    Identity is (source, external_id) — the connector's own grouping key —
    never the display name, which can change on the source side.
    """

    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_group_source_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50))
    external_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(1000), default="")
    active: Mapped[bool] = mapped_column(default=True)


class GroupMembership(Base):
    __tablename__ = "group_memberships"

    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)


class DirectorySyncRun(Base):
    """One execution of a directory sync (spec §28) — the record an admin
    reads after clicking "Synchroniser maintenant"."""

    __tablename__ = "directory_sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    users_added: Mapped[int] = mapped_column(Integer, default=0)
    users_updated: Mapped[int] = mapped_column(Integer, default=0)
    users_deactivated: Mapped[int] = mapped_column(Integer, default=0)
    groups_added: Mapped[int] = mapped_column(Integer, default=0)
    groups_updated: Mapped[int] = mapped_column(Integer, default=0)
    memberships_added: Mapped[int] = mapped_column(Integer, default=0)
    memberships_removed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(2000))


class DirectoryConnectorConfig(Base):
    """Credentials for a remote directory connector (Entra ID, Google
    Workspace), one row per source. Non-secret fields live in
    `settings_json`; the one secret is stored only as `encrypted_secret`,
    AES-GCM ciphertext under the runtime master key (spec §99-101) — never
    in the environment, never returned by the API.
    """

    __tablename__ = "directory_connector_configs"

    source: Mapped[str] = mapped_column(String(50), primary_key=True)
    settings_json: Mapped[str] = mapped_column(String(2000), default="{}")
    encrypted_secret: Mapped[str | None] = mapped_column(String(10000))
    # Scheduled sync (spec §15): run this source every N minutes; None = manual.
    sync_interval_minutes: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
