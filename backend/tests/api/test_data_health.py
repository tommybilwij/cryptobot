"""Tests for /api/v1/data-health endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_health_event import DataHealthEvent


@pytest.mark.asyncio
async def test_recent_returns_events(async_client: AsyncClient, db_session: AsyncSession) -> None:
    event = DataHealthEvent(
        event_type="gap",
        exchange="binance",
        symbol="BTCUSDT",
        data_type="kline_1m",
        severity="warning",
        description="3-minute gap on 2026-04-15",
        details={"gap_start_ms": 1714521600000, "gap_end_ms": 1714521780000},
    )
    db_session.add(event)
    await db_session.flush()
    await db_session.commit()

    r = await async_client.get("/api/v1/data-health/recent")
    assert r.status_code == 200
    body = r.json()
    assert any(e["event_type"] == "gap" for e in body)
