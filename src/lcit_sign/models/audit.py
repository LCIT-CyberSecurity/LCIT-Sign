from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from lcit_sign.database import Base

# Genesis hash the chain starts from — the previous_event_hash of the very
# first audit row ever written. Fixed so a restored/empty database always
# resumes the chain from the same known point.
GENESIS_HASH = "0" * 64


class AuditChainState(Base):
    """Singleton row holding the tip of the audit hash chain.

    Appending an event takes `SELECT ... FOR UPDATE` on this row inside the
    same transaction as the insert, which is what actually serializes
    concurrent writers — the row's own columns are a convenience mirror of
    the last AuditEvent, not the source of truth for anything else.
    """

    __tablename__ = "audit_chain_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    last_event_hash: Mapped[str] = mapped_column(String(64), default=GENESIS_HASH)


class AuditEvent(Base):
    """An append-only business audit trail entry (spec §93-96).

    Distinct from technical logs: this is what proves *who did what, to
    what, when* for compliance and incident review. Never updated or
    deleted through the normal API — only inserted.
    """

    __tablename__ = "audit_events"

    # SQLite only auto-increments a plain INTEGER primary key (its rowid
    # alias), not BIGINT — the variant keeps Postgres on a real bigserial
    # while letting sqlite (used in tests) generate values the same way.
    sequence: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(unique=True, default=uuid.uuid4)
    timestamp_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    actor_id: Mapped[uuid.UUID | None]
    actor_identity_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(255))

    campaign_id: Mapped[uuid.UUID | None]
    document_id: Mapped[uuid.UUID | None]
    signature_id: Mapped[uuid.UUID | None]

    request_id: Mapped[str | None] = mapped_column(String(64))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(32), default="SUCCESS")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    previous_event_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)
