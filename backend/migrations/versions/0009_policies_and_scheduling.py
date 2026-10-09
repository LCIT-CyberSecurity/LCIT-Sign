"""Reminder/renewal policies, re-signing across campaigns, scheduled sync.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("reminder_first_days", sa.Integer()))
    op.add_column("campaigns", sa.Column("reminder_interval_days", sa.Integer()))
    op.add_column("campaigns", sa.Column("reminder_max_count", sa.Integer()))
    op.add_column("campaigns", sa.Column("reminder_before_deadline_days", sa.Integer()))
    op.add_column("campaigns", sa.Column("renewal_every", sa.Integer()))
    op.add_column("campaigns", sa.Column("renewal_unit", sa.String(10)))
    op.add_column("campaigns", sa.Column("renewed_at", sa.DateTime(timezone=True)))
    op.add_column("campaigns", sa.Column("renewal_of_campaign_id", sa.Uuid()))

    # A user may sign the same version again in a later campaign (periodic
    # or manual re-signature, spec §29/§51) — the old signature is never
    # touched. Idempotency is now per campaign.
    op.drop_constraint("uq_signature_user_version", "signatures", type_="unique")
    op.create_unique_constraint(
        "uq_signature_user_version_campaign",
        "signatures",
        ["user_id", "document_version_id", "campaign_id"],
    )
    op.create_index(
        "uq_signature_user_version_no_campaign",
        "signatures",
        ["user_id", "document_version_id"],
        unique=True,
        postgresql_where=sa.text("campaign_id IS NULL"),
    )

    op.add_column(
        "directory_connector_configs", sa.Column("sync_interval_minutes", sa.Integer())
    )


def downgrade() -> None:
    op.drop_column("directory_connector_configs", "sync_interval_minutes")
    op.drop_index("uq_signature_user_version_no_campaign", table_name="signatures")
    op.drop_constraint("uq_signature_user_version_campaign", "signatures", type_="unique")
    op.create_unique_constraint(
        "uq_signature_user_version", "signatures", ["user_id", "document_version_id"]
    )
    for column in (
        "renewal_of_campaign_id", "renewed_at", "renewal_unit", "renewal_every",
        "reminder_before_deadline_days", "reminder_max_count",
        "reminder_interval_days", "reminder_first_days",
    ):
        op.drop_column("campaigns", column)
