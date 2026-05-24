"""create_decision_audit_entries

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-24 13:44:12.518834

"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "decision_audit_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strategy_name", sa.String(length=80), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_type", sa.String(length=20), nullable=False),
        sa.Column(
            "input_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "orders",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "fills",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("reconciliation_status", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["strategy_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_decision_audit_profile_hash_ts",
        "decision_audit_entries",
        ["profile_hash", "ts"],
        unique=False,
    )
    op.create_index(
        "ix_decision_audit_strategy_ts",
        "decision_audit_entries",
        ["strategy_name", "ts"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_decision_audit_strategy_ts", table_name="decision_audit_entries"
    )
    op.drop_index(
        "ix_decision_audit_profile_hash_ts", table_name="decision_audit_entries"
    )
    op.drop_table("decision_audit_entries")
