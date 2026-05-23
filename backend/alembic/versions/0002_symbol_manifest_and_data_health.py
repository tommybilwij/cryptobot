"""symbol_manifest_and_data_health

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-24 07:56:50.559963

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_health_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("exchange", sa.String(length=40), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=True),
        sa.Column("data_type", sa.String(length=40), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "symbol_manifest_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("exchange", sa.String(length=40), nullable=False),
        sa.Column(
            "symbols",
            postgresql.ARRAY(sa.String(length=40)),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_date", "exchange", name="uq_manifest_snapshot"
        ),
    )


def downgrade() -> None:
    op.drop_table("symbol_manifest_snapshots")
    op.drop_table("data_health_events")
