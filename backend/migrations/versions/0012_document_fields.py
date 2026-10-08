"""Prepared elements on documents (signature, date, text, logo...) and their values.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "document_fields",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_version_id", sa.Uuid(), sa.ForeignKey("document_versions.id"), nullable=False
        ),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("label", sa.String(120), nullable=False, server_default=""),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("role", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("group_key", sa.String(60)),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_document_fields_version", "document_fields", ["document_version_id"])
    op.add_column("signatures", sa.Column("field_values", sa.JSON()))


def downgrade() -> None:
    op.drop_column("signatures", "field_values")
    op.drop_index("ix_document_fields_version", table_name="document_fields")
    op.drop_table("document_fields")
