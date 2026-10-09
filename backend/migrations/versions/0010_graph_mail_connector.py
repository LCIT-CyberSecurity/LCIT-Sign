"""Microsoft Graph mail connector (Phase 5).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.add_column(
        "mail_connectors",
        sa.Column("kind", sa.String(10), nullable=False, server_default="smtp"),
    )
    op.add_column("mail_connectors", sa.Column("graph_tenant_id", sa.String(100)))
    op.add_column("mail_connectors", sa.Column("graph_client_id", sa.String(100)))
    op.alter_column("mail_connectors", "host", server_default="")


def downgrade() -> None:
    op.alter_column("mail_connectors", "host", server_default=None)
    op.drop_column("mail_connectors", "graph_client_id")
    op.drop_column("mail_connectors", "graph_tenant_id")
    op.drop_column("mail_connectors", "kind")
