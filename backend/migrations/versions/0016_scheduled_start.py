"""A campaign can be sent for a later start date.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("scheduled_start", sa.DateTime(timezone=True)))
    op.add_column("campaigns", sa.Column("launch_request", sa.JSON()))


def downgrade() -> None:
    op.drop_column("campaigns", "launch_request")
    op.drop_column("campaigns", "scheduled_start")
