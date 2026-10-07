"""Everyone can sign by default: give the signer role to the active people who have no role at all
(the ones a directory import created before this became the default).

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-08

Somebody who already has a role (an administrator, an operator, a preparer) is left as an
administrator set them up; the role can still be taken away afterwards.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id FROM users WHERE active = :yes"
            " AND id NOT IN (SELECT user_id FROM user_roles)"
        ),
        {"yes": True},
    ).fetchall()
    user_roles = sa.table(
        "user_roles", sa.column("user_id", sa.Uuid()), sa.column("role", sa.String())
    )
    if rows:
        op.bulk_insert(user_roles, [{"user_id": r[0], "role": "SIGNER"} for r in rows])


def downgrade() -> None:
    pass  # the role was given on purpose; nothing to undo
