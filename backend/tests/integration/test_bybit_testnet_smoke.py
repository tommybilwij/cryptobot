"""Integration smoke: BybitExchange against real Bybit Testnet (V5 unified).

Marked ``slow``. Requires BYBIT_API_KEY + BYBIT_API_SECRET env vars (testnet).

Run via: cd backend && uv run pytest -m slow tests/integration/test_bybit_testnet_smoke.py -v
"""

from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

from app.exchanges.bybit import BybitExchange
from app.exchanges.types import Balance
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.slow
@pytest.mark.asyncio
async def test_bybit_testnet_fetch_balance() -> None:
    key = os.environ.get("BYBIT_API_KEY")
    secret = os.environ.get("BYBIT_API_SECRET")
    if not key or not secret:
        pytest.skip("requires BYBIT_API_KEY + BYBIT_API_SECRET env vars")

    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BybitExchange(
            fetcher=fetcher,
            params=_params(),
            api_key=key,
            api_secret=secret,
            base_url="https://api-testnet.bybit.com",
        )
        balance = await ex.fetch_balance("USDT")
    assert isinstance(balance, Balance)
    assert balance.venue == "bybit"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_bybit_testnet_fetch_positions() -> None:
    key = os.environ.get("BYBIT_API_KEY")
    secret = os.environ.get("BYBIT_API_SECRET")
    if not key or not secret:
        pytest.skip("requires BYBIT_API_KEY + BYBIT_API_SECRET env vars")

    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BybitExchange(
            fetcher=fetcher,
            params=_params(),
            api_key=key,
            api_secret=secret,
            base_url="https://api-testnet.bybit.com",
        )
        positions = await ex.fetch_positions()
    assert isinstance(positions, tuple)
