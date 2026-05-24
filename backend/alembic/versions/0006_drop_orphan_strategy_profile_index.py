"""drop_orphan_strategy_profile_index

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-24

The ``ix_strategy_profiles_active`` btree index on ``strategy_profiles.is_active``
was created by Phase 3 but its lookup pattern was never actually used at runtime —
queries always go by ``id`` or ``name``. ``if_exists`` keeps the migration
idempotent so it's safe to run on environments that already lack the index.

"""

from __future__ import annotations

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_index(
        "ix_strategy_profiles_active",
        table_name="strategy_profiles",
        if_exists=True,
    )


def downgrade() -> None:
    # Recreate the index in case downgrade is needed.
    op.create_index(
        "ix_strategy_profiles_active",
        "strategy_profiles",
        ["is_active"],
        unique=False,
        if_not_exists=True,
    )
