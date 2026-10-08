"""Encrypted credentials for remote directory connectors (Phase 6).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "directory_connector_configs",
        sa.Column("source", sa.String(50), primary_key=True),
        sa.Column("settings_json", sa.String(2000), nullable=False),
        sa.Column("encrypted_secret", sa.String(10000)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id")),
    )


def downgrade() -> None:
    op.drop_table("directory_connector_configs")
