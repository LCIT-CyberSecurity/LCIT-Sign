"""Document description and category (Phase 2, spec §26).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("description", sa.String(2000), nullable=False, server_default=""),
    )
    op.add_column(
        "documents",
        sa.Column("category", sa.String(100), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("documents", "category")
    op.drop_column("documents", "description")
