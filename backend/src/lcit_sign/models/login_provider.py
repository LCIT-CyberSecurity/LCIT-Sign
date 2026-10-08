from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from lcit_sign.database import Base


class LoginProvider(Base):
    """A sign-in button an administrator set up by hand: "entra" (Microsoft) or "google". The
    application's client id is not secret; its secret is stored only as AES-GCM ciphertext under
    the master key, like the directory connectors. Nothing of this lives in the environment."""

    __tablename__ = "login_providers"

    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(255))
    tenant_id: Mapped[str | None] = mapped_column(String(255))
    encrypted_secret: Mapped[str] = mapped_column(String(10000))
    # One sign-in provider is active at a time (the one the login page offers).
    active: Mapped[bool] = mapped_column(default=False, server_default="0")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
