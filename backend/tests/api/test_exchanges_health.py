"""Tests for /api/v1/exchanges/health."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_three_venues(async_client: AsyncClient) -> None:
    r = await async_client.get("/api/v1/exchanges/health")
    assert r.status_code == 200
    body = r.json()
    names = {v["name"] for v in body["venues"]}
    assert names == {"binance", "bybit", "hyperliquid"}
    # PaperExchange is always reachable in tests
    for v in body["venues"]:
        assert v["reachable"] is True
        assert v["balance_quote"] == 10_000.0
