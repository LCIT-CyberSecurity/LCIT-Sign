"""Directory (groups) and group-based campaign targeting (Phase 6).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("source", "external_id", name="uq_group_source_external_id"),
    )

    op.create_table(
        "group_memberships",
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
    )

    op.create_table(
        "directory_sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="RUNNING"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("users_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("users_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("users_deactivated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("groups_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("groups_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("memberships_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("memberships_removed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(2000), nullable=True),
    )

    op.create_table(
        "campaign_target_groups",
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id"), primary_key=True),
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id"), primary_key=True),
    )

    # target_mode becomes a free-form display label (ALL_USERS / GROUPS /
    # SPECIFIC_USERS / GROUPS_AND_USERS computed at launch), no longer a
    # DB-checked enum — dropping and re-adding the column is simplest and
    # safe: no production campaigns exist yet to preserve.
    op.drop_column("campaigns", "target_mode")
    op.add_column(
        "campaigns",
        sa.Column(
            "target_mode", sa.String(30), nullable=False, server_default="SPECIFIC_USERS"
        ),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "target_mode")
    op.add_column(
        "campaigns",
        sa.Column(
            "target_mode",
            sa.Enum(
                "ALL_USERS", "SPECIFIC_USERS",
                name="campaign_target_mode", native_enum=False, length=20,
            ),
            nullable=False,
            server_default="SPECIFIC_USERS",
        ),
    )
    op.drop_table("campaign_target_groups")
    op.drop_table("directory_sync_runs")
    op.drop_table("group_memberships")
    op.drop_table("groups")
