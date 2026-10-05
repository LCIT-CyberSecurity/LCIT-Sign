"""Mail connector and notification queue (Phase 5).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "mail_connectors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("use_tls", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("use_starttls", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("username", sa.String(255), nullable=False, server_default=""),
        sa.Column("encrypted_password", sa.String(1000), nullable=True),
        sa.Column("from_address", sa.String(320), nullable=False),
        sa.Column("reply_to", sa.String(320), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "notification_type",
            sa.Enum(
                "DOCUMENT_TO_SIGN", "REMINDER", "SIGNATURE_CONFIRMATION", "TEST_EMAIL",
                name="notification_type", native_enum=False, length=32,
            ),
            nullable=False,
        ),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body_text", sa.String(10000), nullable=False),
        sa.Column(
            "related_assignment_id",
            sa.Uuid(),
            sa.ForeignKey("signature_assignments.id"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "PROCESSING", "SENT", "FAILED", "RETRY",
                name="notification_status", native_enum=False, length=20,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(1000), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notifications_status_next_attempt", "notifications", ["status", "next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("mail_connectors")
