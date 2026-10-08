"""Signature reports / procès-verbaux (Phase 7).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("generated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("pdf_sha256", sa.String(64), nullable=False),
        sa.Column("csv_sha256", sa.String(64), nullable=False),
        sa.Column("signing_key_id", sa.String(64), nullable=False),
        sa.Column("cryptographic_signature", sa.String(255), nullable=False),
    )
    op.create_index("ix_reports_campaign_id", "reports", ["campaign_id"])


def downgrade() -> None:
    op.drop_table("reports")
