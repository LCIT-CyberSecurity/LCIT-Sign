"""Sign-in providers (Microsoft, Google) set up by an administrator, secret encrypted.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "login_providers",
        sa.Column("provider", sa.String(20), primary_key=True),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("tenant_id", sa.String(255)),
        sa.Column("encrypted_secret", sa.String(10000), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("login_providers")
