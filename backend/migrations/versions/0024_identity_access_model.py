"""Identity and access, simplified: SIGNER is the standard role of every active person, the global
PREPARER role goes away, and one sign-in provider and one directory are active at a time.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-08

* every active user without SIGNER gets it (administrators and operators included);
* whoever held PREPARER gets SIGNER (active or not), then the PREPARER rows are removed: what
  they could do, any signer can. CampaignPreparer (a right on ONE campaign) is untouched;
* `login_providers.active` / `directory_connector_configs.active`: the one in use. An existing
  installation keeps working: Microsoft (else Google) is the active sign-in, and the most recently
  updated remote directory is the active one.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # Former preparers keep what they could do: they become signers (any state).
    bind.execute(
        sa.text(
            "INSERT INTO user_roles (user_id, role, granted_at)"
            " SELECT DISTINCT p.user_id, 'SIGNER', CURRENT_TIMESTAMP FROM user_roles p"
            " WHERE p.role = 'PREPARER' AND NOT EXISTS ("
            "   SELECT 1 FROM user_roles s WHERE s.user_id = p.user_id AND s.role = 'SIGNER')"
        )
    )
    bind.execute(sa.text("DELETE FROM user_roles WHERE role = 'PREPARER'"))
    # Everyone active can sign by default, whatever else they are.
    bind.execute(
        sa.text(
            "INSERT INTO user_roles (user_id, role, granted_at)"
            " SELECT u.id, 'SIGNER', CURRENT_TIMESTAMP FROM users u WHERE u.active = :yes"
            " AND NOT EXISTS ("
            "   SELECT 1 FROM user_roles s WHERE s.user_id = u.id AND s.role = 'SIGNER')"
        ),
        {"yes": True},
    )

    op.add_column(
        "login_providers",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "directory_connector_configs",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    chosen = bind.execute(
        sa.text(
            "SELECT provider FROM login_providers"
            " ORDER BY CASE provider WHEN 'entra' THEN 0 ELSE 1 END LIMIT 1"
        )
    ).scalar()
    if chosen:
        bind.execute(
            sa.text("UPDATE login_providers SET active = :yes WHERE provider = :p"),
            {"yes": True, "p": chosen},
        )
    directory = bind.execute(
        sa.text(
            "SELECT source FROM directory_connector_configs WHERE source <> 'local'"
            " AND encrypted_secret IS NOT NULL ORDER BY updated_at DESC LIMIT 1"
        )
    ).scalar()
    if directory:
        bind.execute(
            sa.text("UPDATE directory_connector_configs SET active = :yes WHERE source = :s"),
            {"yes": True, "s": directory},
        )


def downgrade() -> None:
    op.drop_column("directory_connector_configs", "active")
    op.drop_column("login_providers", "active")
    # The roles stay as they are: SIGNER was given on purpose and PREPARER is not coming back.
