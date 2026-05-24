"""Tests for ``/api/v1/live`` endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile


@pytest.mark.asyncio
async def test_status_returns_default_state(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    """No active profile → response reflects registry defaults."""
    r = await async_client.get("/api/v1/live/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["dry_run_mode"] is True
    assert body["venue"] == "binance"
    assert body["last_tick_ts"] is None
    assert body["peak_equity_quote"] == 0.0


@pytest.mark.asyncio
async def test_status_reflects_active_profile_flags(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Active profile with ``live.enabled=True`` → response shows True."""
    profile = StrategyProfile(
        name="live-on",
        version=1,
        is_active=True,
        config={"live": {"enabled": True}},
    )
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    r = await async_client.get("/api/v1/live/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True


@pytest.mark.asyncio
async def test_stop_flips_enabled_to_false(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /stop flips ``live.enabled`` False and bumps version."""
    profile = StrategyProfile(
        name="live-stop",
        version=1,
        is_active=True,
        config={"live": {"enabled": True}},
    )
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    r = await async_client.post("/api/v1/live/stop")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["live_enabled"] is False
    assert body["new_version"] == 2
    assert body["active_profile_id"] == str(profile.id)
