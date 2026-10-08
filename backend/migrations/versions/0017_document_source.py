"""Hash of the Word / LibreOffice source a document version was converted from.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-06

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.add_column("document_versions", sa.Column("source_sha256", sa.String(64)))


def downgrade() -> None:
    op.drop_column("document_versions", "source_sha256")
