"""Integration smoke: BinanceExchange against real Binance Spot Testnet.

Marked ``slow`` (deselected by default). Requires:
  - BINANCE_API_KEY + BINANCE_API_SECRET env vars (testnet keys)
  - testnet wallet seeded via https://testnet.binance.vision/

Run via: cd backend && uv run pytest -m slow tests/integration/test_binance_testnet_smoke.py -v
"""

from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

from app.exchanges.binance import BinanceExchange
from app.exchanges.types import Balance
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.slow
@pytest.mark.asyncio
async def test_binance_testnet_fetch_balance() -> None:
    key = os.environ.get("BINANCE_API_KEY")
    secret = os.environ.get("BINANCE_API_SECRET")
    if not key or not secret:
        pytest.skip("requires BINANCE_API_KEY + BINANCE_API_SECRET env vars")

    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher,
            params=_params(),
            api_key=key,
            api_secret=secret,
            base_url="https://testnet.binance.vision",
        )
        balance = await ex.fetch_balance("USDT")
    assert isinstance(balance, Balance)
    assert balance.venue == "binance"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_binance_testnet_fetch_positions() -> None:
    key = os.environ.get("BINANCE_API_KEY")
    secret = os.environ.get("BINANCE_API_SECRET")
    if not key or not secret:
        pytest.skip("requires BINANCE_API_KEY + BINANCE_API_SECRET env vars")

    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher,
            params=_params(),
            api_key=key,
            api_secret=secret,
            base_url="https://testnet.binancefuture.com",
        )
        positions = await ex.fetch_positions()
    assert isinstance(positions, tuple)
