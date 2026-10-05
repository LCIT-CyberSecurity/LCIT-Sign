"""Signing keys and signatures (Phase 3).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "signing_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key_id", sa.String(64), nullable=False, unique=True),
        sa.Column("public_key_hex", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE", "RETIRED", "REVOKED",
                name="signing_key_status", native_enum=False, length=20,
            ),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "signatures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column(
            "document_version_id", sa.Uuid(), sa.ForeignKey("document_versions.id"), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("identity_provider", sa.String(255), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email_snapshot", sa.String(320), nullable=False),
        sa.Column("display_name_snapshot", sa.String(255), nullable=False),
        sa.Column("consent_text", sa.String(1000), nullable=False),
        sa.Column("consent_version", sa.String(50), nullable=False),
        sa.Column("signed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_file_sha256", sa.String(64), nullable=False),
        sa.Column("signed_file_sha256", sa.String(64), nullable=False),
        sa.Column("application_version", sa.String(50), nullable=False),
        sa.Column("signing_key_id", sa.String(64), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("cryptographic_signature", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "document_version_id", name="uq_signature_user_version"),
    )
    op.create_index("ix_signatures_user_id", "signatures", ["user_id"])
    op.create_index("ix_signatures_document_version_id", "signatures", ["document_version_id"])


def downgrade() -> None:
    op.drop_table("signatures")
    op.drop_table("signing_keys")
