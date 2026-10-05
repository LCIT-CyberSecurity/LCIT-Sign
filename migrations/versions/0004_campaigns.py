"""Campaigns, targeting, and signature assignments (Phase 4).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT", "ACTIVE", "CLOSED", "CANCELLED", "ARCHIVED",
                name="campaign_status", native_enum=False, length=20,
            ),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "target_mode",
            sa.Enum(
                "ALL_USERS", "SPECIFIC_USERS",
                name="campaign_target_mode", native_enum=False, length=20,
            ),
            nullable=False,
            server_default="SPECIFIC_USERS",
        ),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("launch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "campaign_documents",
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id"), primary_key=True),
        sa.Column(
            "document_version_id",
            sa.Uuid(),
            sa.ForeignKey("document_versions.id"),
            primary_key=True,
        ),
    )

    op.create_table(
        "campaign_target_users",
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
    )

    op.create_table(
        "signature_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column(
            "document_version_id", sa.Uuid(), sa.ForeignKey("document_versions.id"), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "VIEWED", "SIGNED", "EXPIRED", "CANCELLED",
                name="assignment_status", native_enum=False, length=20,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("first_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signature_id", sa.Uuid(), sa.ForeignKey("signatures.id"), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "campaign_id", "document_version_id", "user_id", name="uq_assignment_campaign_doc_user"
        ),
    )
    op.create_index(
        "ix_signature_assignments_user_id", "signature_assignments", ["user_id"]
    )
    op.create_index(
        "ix_signature_assignments_campaign_id", "signature_assignments", ["campaign_id"]
    )


def downgrade() -> None:
    op.drop_table("signature_assignments")
    op.drop_table("campaign_target_users")
    op.drop_table("campaign_documents")
    op.drop_table("campaigns")
