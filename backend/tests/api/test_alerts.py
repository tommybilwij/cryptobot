"""Tests for /api/v1/alerts/test."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile


@pytest.mark.asyncio
async def test_no_webhook_returns_not_configured(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    p = StrategyProfile(name="alert-test", version=1, is_active=True, config={})
    db_session.add(p)
    await db_session.flush()
    await db_session.commit()
    r = await async_client.post("/api/v1/alerts/test")
    assert r.status_code == 200
    body = r.json()
    assert body["webhook_url_configured"] is False
    assert body["sent"] is False


@pytest.mark.asyncio
async def test_no_active_profile_returns_422(async_client: AsyncClient) -> None:
    r = await async_client.post("/api/v1/alerts/test")
    assert r.status_code == 422
