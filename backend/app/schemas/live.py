"""Pydantic v2 schemas for ``/api/v1/live`` endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LiveStatusResponse(BaseModel):
    """Snapshot of the live runner state for ``GET /api/v1/live/status``."""

    enabled: bool
    dry_run_mode: bool
    venue: str
    last_tick_ts: datetime | None
    last_reconciliation_status: str | None
    last_equity_quote: float | None
    peak_equity_quote: float
    drawdown_pct: float | None


class LiveStopResponse(BaseModel):
    """Result of ``POST /api/v1/live/stop`` — flipped flag + bumped version."""

    active_profile_id: str
    live_enabled: bool
    new_version: int
