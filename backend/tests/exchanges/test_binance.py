"""Tests for BinanceExchange REST adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.backtest.orders import Order
from app.exchanges.binance import BinanceExchange
from app.exchanges.errors import AuthFailed
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.asyncio
async def test_fetch_balance_parses_response() -> None:
    def handler(req: Request) -> Response:
        # Signed-GET smoke check: HMAC header + signature query param present.
        assert "X-MBX-APIKEY" in req.headers
        assert "signature=" in req.url.query.decode()
        return Response(
            200,
            json={
                "balances": [
                    {"asset": "USDC", "free": "9876.5", "locked": "100.0"},
                    {"asset": "BTC", "free": "0.1", "locked": "0.0"},
                ]
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="test-key",
            api_secret="test-secret",
            base_url="https://testnet.binance.vision",
        )
        b = await ex.fetch_balance("USDC")
    assert b.free == 9876.5
    assert b.locked == 100.0
    assert b.quote_currency == "USDC"


@pytest.mark.asyncio
async def test_place_market_order_returns_receipt() -> None:
    # place_order spins up its own httpx.AsyncClient, so MockTransport on the
    # shared fetcher's client wouldn't intercept it. Patch AsyncClient.post
    # at the class level instead.
    captured: dict[str, Any] = {}

    async def mock_post(
        self: httpx.AsyncClient,
        url: str,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        captured["url"] = url
        captured["headers"] = dict(kwargs.get("headers", {}))
        return Response(
            200,
            json={
                "orderId": 12345,
                "symbol": "BTCUSDT",
                "transactTime": 1714521600000,
            },
        )

    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="test-key",
            api_secret="test-secret",
            base_url="https://testnet.binance.vision",
        )
        order = Order(
            venue="binance",
            symbol="BTCUSDT",
            product="spot",
            side="buy",
            qty_base=0.1,
            order_type="market",
        )
        with patch.object(httpx.AsyncClient, "post", mock_post):
            receipt = await ex.place_order(order)

    assert receipt.order_id == "12345"
    assert receipt.venue == "binance"
    assert receipt.symbol == "BTCUSDT"
    assert receipt.submitted_ts_ms == 1714521600000
    assert "signature=" in captured["url"]
    assert captured["headers"]["X-MBX-APIKEY"] == "test-key"


@pytest.mark.asyncio
async def test_binance_fetch_positions_parses_position_risk() -> None:
    def handler(req: Request) -> Response:
        assert "/fapi/v2/positionRisk" in req.url.path
        return Response(
            200,
            json=[
                {
                    "symbol": "BTCUSDT",
                    "positionAmt": "-0.5",
                    "entryPrice": "60000.0",
                    "markPrice": "60100.0",
                    "unRealizedProfit": "-50.0",
                },
                {
                    "symbol": "ETHUSDT",
                    "positionAmt": "0",
                    "entryPrice": "0",
                    "markPrice": "3000.0",
                    "unRealizedProfit": "0",
                },
            ],
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="t",
            api_secret="t",
            base_url="https://testnet.binancefuture.com",
        )
        positions = await ex.fetch_positions()
    # Zero-qty placeholder row is filtered out.
    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].qty_base == -0.5
    assert positions[0].product == "perp"


@pytest.mark.asyncio
async def test_binance_fetch_funding_rate_parses_premium_index() -> None:
    def handler(req: Request) -> Response:
        assert "/fapi/v1/premiumIndex" in req.url.path
        return Response(
            200,
            json={
                "symbol": "BTCUSDT",
                "markPrice": "60100.0",
                "lastFundingRate": "0.0001",
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="t",
            api_secret="t",
            base_url="https://testnet.binancefuture.com",
        )
        rate = await ex.fetch_funding_rate("BTCUSDT")
    assert rate == 0.0001


@pytest.mark.asyncio
async def test_binance_fetch_order_parses_open_order() -> None:
    def handler(req: Request) -> Response:
        # Signed-GET with symbol + orderId in the query string.
        query = req.url.query.decode()
        assert "symbol=BTCUSDT" in query
        assert "orderId=12345" in query
        return Response(
            200,
            json={
                "orderId": 12345,
                "symbol": "BTCUSDT",
                "status": "FILLED",
                "executedQty": "0.1",
                "cummulativeQuoteQty": "6003.0",
                "side": "BUY",
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="t",
            api_secret="t",
            base_url="https://testnet.binance.vision",
        )
        status = await ex.fetch_order("12345", symbol="BTCUSDT")
    assert status.status == "filled"
    assert status.filled_qty_base == 0.1
    assert status.fill_px == 60030.0


@pytest.mark.asyncio
async def test_auth_failure_raises() -> None:
    def handler(req: Request) -> Response:
        return Response(401, json={"code": -2014, "msg": "API-key format invalid."})

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, max_retries=0, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="bad",
            api_secret="bad",
            base_url="https://testnet.binance.vision",
        )
        with pytest.raises(AuthFailed):
            await ex.fetch_balance("USDC")
