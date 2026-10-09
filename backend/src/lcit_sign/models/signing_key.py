from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from lcit_sign.database import Base


class SigningKeyStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    REVOKED = "REVOKED"


class SigningKey(Base):
    """An application signing key (spec §65-66).

    Only the public key is stored. The private Ed25519 seed is never
    persisted anywhere — it is re-derived on demand from
    `LCIT_SIGN_MASTER_KEY` and this row's `key_id` via HKDF (see
    `lcit_sign.services.signing`). Rotating a key means minting a new
    key_id; old public keys stay forever so old signatures stay verifiable.
    """

    __tablename__ = "signing_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key_id: Mapped[str] = mapped_column(String(64), unique=True)
    public_key_hex: Mapped[str] = mapped_column(String(64))
    status: Mapped[SigningKeyStatus] = mapped_column(
        Enum(SigningKeyStatus, native_enum=False, length=20), default=SigningKeyStatus.ACTIVE
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
