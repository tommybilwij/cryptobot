"""Chaos: httpx ConnectionError bubbles cleanly."""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ConnectError, MockTransport, Request

from app.exchanges.binance import BinanceExchange
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.slow
@pytest.mark.asyncio
async def test_connection_error_raises_runtime_error() -> None:
    def handler(req: Request):
        raise ConnectError("network unreachable")

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, max_retries=1, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher, params=_params(),
            api_key="k", api_secret="s",
            base_url="https://testnet.binance.vision",
        )
        with pytest.raises(RuntimeError):
            await ex.fetch_balance("USDC")
