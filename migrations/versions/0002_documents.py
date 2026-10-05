"""Documents and document versions (Phase 2).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_label", sa.String(50), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT", "PUBLISHED", "SUPERSEDED", "ARCHIVED",
                name="document_version_status", native_enum=False, length=20,
            ),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_document_versions_document_id", "document_versions", ["document_id"]
    )


def downgrade() -> None:
    op.drop_table("document_versions")
    op.drop_table("documents")
