"""Campaign owner (apart from the creator), campaign preparers; the PREPARER role.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-07

The role column is a plain VARCHAR(20) ("native_enum=False"), so PREPARER needs no change to it.
Existing campaigns keep working: their owner starts as their creator (created_by is never touched).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id")))
    op.execute("UPDATE campaigns SET owner_id = created_by")
    op.create_table(
        "campaign_preparers",
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("added_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("campaign_preparers")
    op.drop_column("campaigns", "owner_id")
