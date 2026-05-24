"""Tests for BybitExchange V5 REST adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.backtest.orders import Order
from app.exchanges.bybit import BybitExchange
from app.exchanges.errors import AuthFailed
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.asyncio
async def test_fetch_balance_parses_v5_response() -> None:
    def handler(req: Request) -> Response:
        # Signed-GET smoke check: Bybit V5 HMAC headers present.
        assert req.headers.get("X-BAPI-API-KEY") == "test-key"
        assert "X-BAPI-SIGN" in req.headers
        assert req.headers.get("X-BAPI-TIMESTAMP")
        assert req.headers.get("X-BAPI-RECV-WINDOW") == "5000"
        return Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "list": [
                        {
                            "coin": [
                                {
                                    "coin": "USDT",
                                    "free": "5000.0",
                                    "locked": "0.0",
                                }
                            ]
                        }
                    ]
                },
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BybitExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="test-key",
            api_secret="test-secret",
            base_url="https://api-testnet.bybit.com",
        )
        b = await ex.fetch_balance("USDT")
    assert b.free == 5000.0
    assert b.locked == 0.0
    assert b.quote_currency == "USDT"
    assert b.venue == "bybit"


@pytest.mark.asyncio
async def test_place_market_order_returns_order_id() -> None:
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
        captured["content"] = kwargs.get("content")
        return Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {"orderId": "abc-123", "orderLinkId": "x"},
            },
        )

    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BybitExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="t",
            api_secret="t",
            base_url="https://api-testnet.bybit.com",
        )
        order = Order(
            venue="bybit",
            symbol="BTCUSDT",
            product="perp",
            side="sell",
            qty_base=0.05,
            order_type="market",
        )
        with patch.object(httpx.AsyncClient, "post", mock_post):
            receipt = await ex.place_order(order)

    assert receipt.order_id == "abc-123"
    assert receipt.venue == "bybit"
    assert receipt.symbol == "BTCUSDT"
    assert receipt.submitted_ts_ms > 0
    assert "/v5/order/create" in captured["url"]
    assert captured["headers"]["X-BAPI-API-KEY"] == "t"
    assert "X-BAPI-SIGN" in captured["headers"]


@pytest.mark.asyncio
async def test_bybit_fetch_positions_parses_position_list() -> None:
    def handler(req: Request) -> Response:
        assert "/v5/position/list" in req.url.path
        # Bybit V5 requires category + settleCoin in the position query.
        query = req.url.query.decode()
        assert "category=linear" in query
        assert "settleCoin=USDT" in query
        return Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "list": [
                        {
                            "symbol": "BTCUSDT",
                            "side": "Sell",
                            "size": "0.5",
                            "avgPrice": "60000.0",
                            "markPrice": "60100.0",
                            "unrealisedPnl": "-50.0",
                        },
                        {
                            "symbol": "ETHUSDT",
                            "side": "",
                            "size": "0",
                            "avgPrice": "0",
                            "markPrice": "3000.0",
                            "unrealisedPnl": "0",
                        },
                    ]
                },
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BybitExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="t",
            api_secret="t",
            base_url="https://api-testnet.bybit.com",
        )
        positions = await ex.fetch_positions()
    # Zero-size placeholder filtered; "Sell" side flips sign.
    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].qty_base == -0.5
    assert positions[0].product == "perp"


@pytest.mark.asyncio
async def test_bybit_fetch_funding_rate_parses_history() -> None:
    def handler(req: Request) -> Response:
        assert "/v5/market/funding/history" in req.url.path
        query = req.url.query.decode()
        assert "category=linear" in query
        assert "symbol=BTCUSDT" in query
        return Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "list": [
                        {
                            "symbol": "BTCUSDT",
                            "fundingRate": "0.0001",
                            "fundingRateTimestamp": "1700000000000",
                        }
                    ]
                },
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BybitExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="t",
            api_secret="t",
            base_url="https://api-testnet.bybit.com",
        )
        rate = await ex.fetch_funding_rate("BTCUSDT")
    assert rate == 0.0001


@pytest.mark.asyncio
async def test_bybit_fetch_order_parses_realtime() -> None:
    def handler(req: Request) -> Response:
        assert "/v5/order/realtime" in req.url.path
        query = req.url.query.decode()
        assert "category=linear" in query
        assert "orderId=abc-123" in query
        return Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "list": [
                        {
                            "orderId": "abc-123",
                            "symbol": "BTCUSDT",
                            "orderStatus": "Filled",
                            "cumExecQty": "0.1",
                            "cumExecValue": "6003.0",
                            "cumExecFee": "0.6",
                            "side": "Buy",
                        }
                    ]
                },
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BybitExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="t",
            api_secret="t",
            base_url="https://api-testnet.bybit.com",
        )
        status = await ex.fetch_order("abc-123")
    assert status.status == "filled"
    assert status.filled_qty_base == 0.1
    assert status.fill_px == 60030.0
    assert status.fee_quote == 0.6


@pytest.mark.asyncio
async def test_auth_failure_raises() -> None:
    # Bybit signals auth failure with HTTP 200 + retCode 10003.
    def handler(req: Request) -> Response:
        return Response(
            200, json={"retCode": 10003, "retMsg": "Invalid API key"}
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, max_retries=0, base_backoff_s=0.0)
        ex = BybitExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="bad",
            api_secret="bad",
            base_url="https://api-testnet.bybit.com",
        )
        with pytest.raises(AuthFailed):
            await ex.fetch_balance("USDT")
