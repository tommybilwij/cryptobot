"""SymbolManifestSnapshot ORM: survivorship-safe universe snapshot per venue."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SymbolManifestSnapshot(Base):
    """A snapshot of the top-N symbols by volume on a venue for a given date.

    Used to back-test on the universe AS IT WAS at the date, not as it is
    today (avoids survivorship bias — coins that delisted between snapshot
    date and today still appear in the snapshot).
    """

    __tablename__ = "symbol_manifest_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "exchange", name="uq_manifest_snapshot"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    exchange: Mapped[str] = mapped_column(String(40), nullable=False)
    symbols: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
