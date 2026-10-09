from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from lcit_sign.database import Base


class Report(Base):
    """A signature campaign's procès-verbal (spec §85-87). The PDF is the
    canonical, cryptographically signed artifact; the CSV is a convenience
    export whose hash is recorded alongside it for reference.
    """

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"))
    generated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    pdf_sha256: Mapped[str] = mapped_column(String(64))
    csv_sha256: Mapped[str] = mapped_column(String(64))
    signing_key_id: Mapped[str] = mapped_column(String(64))
    cryptographic_signature: Mapped[str] = mapped_column(String(255))

    @property
    def display_id(self) -> str:
        return f"PV-{self.id.hex[:12].upper()}"
