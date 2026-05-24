"""Chaos: venue returns 503 mid-dispatch."""

from __future__ import annotations

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.exchanges.binance import BinanceExchange
from app.exchanges.errors import Rejected
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.slow
@pytest.mark.asyncio
async def test_venue_returns_503_raises_runtime_error() -> None:
    """When the venue returns 503, the adapter's fetch_balance bubbles RuntimeError."""
    call_count = {"n": 0}

    def handler(req: Request) -> Response:
        call_count["n"] += 1
        return Response(503, text="Service Unavailable")

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, max_retries=1, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher, params=_params(),
            api_key="k", api_secret="s",
            base_url="https://testnet.binance.vision",
        )
        with pytest.raises((Rejected, RuntimeError)):
            await ex.fetch_balance("USDC")
    # Verify retries happened
    assert call_count["n"] >= 1
