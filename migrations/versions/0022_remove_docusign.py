"""Remove DocuSign: its connection, the envelope of each assignment, and the campaign's method.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-08

Signatures already made through DocuSign stay (they are ordinary signatures with their evidence);
only the integration's own tables and column go. Migration 0019, which created them, is kept so
that databases at any revision still upgrade.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.drop_table("docusign_envelopes")
    op.drop_table("docusign_config")
    op.drop_column("campaigns", "signature_method")


def downgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("signature_method", sa.String(20), nullable=False, server_default="LOCAL"),
    )
    op.create_table(
        "docusign_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("environment", sa.String(20), nullable=False),
        sa.Column("integration_key", sa.String(100), nullable=False),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("account_id", sa.String(100), nullable=False),
        sa.Column("auth_url", sa.String(500)),
        sa.Column("api_url", sa.String(500)),
        sa.Column("encrypted_private_key", sa.String(10000)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id")),
    )
    op.create_table(
        "docusign_envelopes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "assignment_id", sa.Uuid(), sa.ForeignKey("signature_assignments.id"),
            nullable=False, unique=True,
        ),
        sa.Column("envelope_id", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String(1000)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
