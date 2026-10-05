"""Signer roles of a campaign and the role of each assignment.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "campaign_roles",
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id"), primary_key=True),
        sa.Column("role", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(100), nullable=False, server_default=""),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id")),
    )
    op.add_column("document_versions", sa.Column("role_labels", sa.JSON()))
    op.add_column("signatures", sa.Column("prior_signatures", sa.JSON()))
    op.add_column(
        "signature_assignments",
        sa.Column("role", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("signature_assignments", "role")
    op.drop_column("document_versions", "role_labels")
    op.drop_column("signatures", "prior_signatures")
    op.drop_table("campaign_roles")
