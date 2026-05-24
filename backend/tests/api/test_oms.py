"""Tests for /api/v1/oms endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile


@pytest.mark.asyncio
async def test_status_returns_kill_switch_false_by_default(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    p = StrategyProfile(name="oms-status-default", version=1, is_active=True, config={})
    db_session.add(p)
    await db_session.flush()
    await db_session.commit()
    r = await async_client.get("/api/v1/oms/status")
    assert r.status_code == 200
    assert r.json()["kill_switch_active"] is False


@pytest.mark.asyncio
async def test_post_kill_flips_flag(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    p = StrategyProfile(name="oms-kill", version=1, is_active=True, config={})
    db_session.add(p)
    await db_session.flush()
    await db_session.commit()
    r = await async_client.post("/api/v1/oms/kill", json={"reason": "test"})
    assert r.status_code == 200
    body = r.json()
    assert body["kill_switch_active"] is True
    # Status endpoint reflects the new state
    s = await async_client.get("/api/v1/oms/status")
    assert s.json()["kill_switch_active"] is True
