"""DecisionAuditEntry ORM — per-decision audit row (Constraint #4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DecisionAuditEntry(Base):
    __tablename__ = "decision_audit_entries"
    __table_args__ = (
        Index("ix_decision_audit_strategy_ts", "strategy_name", "ts"),
        Index("ix_decision_audit_profile_hash_ts", "profile_hash", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(80), nullable=False)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_profiles.id"), nullable=False
    )
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(20), nullable=False)
    input_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    orders: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    fills: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    reconciliation_status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
