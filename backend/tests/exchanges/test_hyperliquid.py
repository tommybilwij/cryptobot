"""Tests for HyperliquidExchange REST adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.backtest.orders import Order
from app.exchanges.hyperliquid import HyperliquidExchange
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams

# Test EVM key (dev only) — deterministic wallet derived from a known constant.
_TEST_KEY = "0x" + "1" * 64


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.asyncio
async def test_fetch_balance_parses_clearinghouse_state() -> None:
    """fetch_balance POSTs clearinghouseState to /info and reads ``withdrawable``."""

    def handler(req: Request) -> Response:
        body = req.content
        # HL's /info accepts JSON; tolerate both compact and spaced forms.
        assert b'"type":"clearinghouseState"' in body or b'"type": "clearinghouseState"' in body
        return Response(
            200,
            json={
                "marginSummary": {
                    "accountValue": "1234.56",
                    "totalRawUsd": "1200.0",
                },
                "withdrawable": "1100.0",
                "assetPositions": [],
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = HyperliquidExchange(
            fetcher=fetcher,
            params=_params(),
            wallet_private_key=_TEST_KEY,
            base_url="https://api.hyperliquid-testnet.xyz",
        )
        b = await ex.fetch_balance("USDC")
    assert b.free == 1100.0
    assert b.quote_currency == "USDC"
    assert b.venue == "hyperliquid"


@pytest.mark.asyncio
async def test_place_order_sends_signed_payload() -> None:
    """place_order signs an envelope and parses oid from ``resting`` status."""
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
        captured["json"] = kwargs.get("json")
        return Response(
            200,
            json={
                "status": "ok",
                "response": {
                    "type": "order",
                    "data": {
                        "statuses": [{"resting": {"oid": 99}}],
                    },
                },
            },
        )

    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = HyperliquidExchange(
            fetcher=fetcher,
            params=_params(),
            wallet_private_key=_TEST_KEY,
            base_url="https://api.hyperliquid-testnet.xyz",
        )
        order = Order(
            venue="hyperliquid",
            symbol="BTC",
            product="perp",
            side="buy",
            qty_base=0.01,
            order_type="market",
        )
        with patch.object(httpx.AsyncClient, "post", mock_post):
            receipt = await ex.place_order(order)

    assert receipt.order_id == "99"
    assert receipt.venue == "hyperliquid"
    assert receipt.symbol == "BTC"
    assert receipt.submitted_ts_ms > 0
    # Signed envelope was sent to /exchange with action/nonce/signature keys.
    assert captured["url"].endswith("/exchange")
    payload = captured["json"]
    assert payload["action"]["type"] == "order"
    assert isinstance(payload["nonce"], int)
    # Phase 7: signature is now an EIP-712 {r, s, v} envelope rather than a
    # personal_sign hex string.
    sig = payload["signature"]
    assert isinstance(sig, dict)
    assert sig["r"].startswith("0x") and len(sig["r"]) == 66
    assert sig["s"].startswith("0x") and len(sig["s"]) == 66
    assert isinstance(sig["v"], int)


@pytest.mark.asyncio
async def test_hl_fetch_order_parses_status() -> None:
    """fetch_order maps HL's status enum to OrderStatus._OrderStatusLiteral."""

    def handler(req: Request) -> Response:
        body = req.content
        assert b'"type":"orderStatus"' in body or b'"type": "orderStatus"' in body
        return Response(
            200,
            json={
                "order": {
                    "status": "filled",
                    "px": "60010",
                    "sz": "0.01",
                }
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = HyperliquidExchange(
            fetcher=fetcher,
            params=_params(),
            wallet_private_key=_TEST_KEY,
            base_url="https://api.hyperliquid-testnet.xyz",
        )
        status = await ex.fetch_order("42")
    assert status.status == "filled"
    assert status.fill_px == 60010.0
    assert status.filled_qty_base == 0.01


@pytest.mark.asyncio
async def test_hl_fetch_funding_rate_parses_history() -> None:
    """fetch_funding_rate reads the last row of HL fundingHistory."""

    def handler(req: Request) -> Response:
        body = req.content
        assert b'"type":"fundingHistory"' in body or b'"type": "fundingHistory"' in body
        # HL returns a JSON array of funding payments.
        return Response(
            200,
            json=[
                {
                    "coin": "BTC",
                    "fundingRate": "0.00005",
                    "premium": "0.0",
                    "time": 1699999999000,
                },
                {
                    "coin": "BTC",
                    "fundingRate": "0.0001",
                    "premium": "0.0",
                    "time": 1700000000000,
                },
            ],
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = HyperliquidExchange(
            fetcher=fetcher,
            params=_params(),
            wallet_private_key=_TEST_KEY,
            base_url="https://api.hyperliquid-testnet.xyz",
        )
        rate = await ex.fetch_funding_rate("BTC")
    assert rate == 0.0001


@pytest.mark.asyncio
async def test_hl_amend_order_raises_not_implemented() -> None:
    """HL has no native amend — Protocol method must raise so callers fall back."""
    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = HyperliquidExchange(
            fetcher=fetcher,
            params=_params(),
            wallet_private_key=_TEST_KEY,
            base_url="https://api.hyperliquid-testnet.xyz",
        )
        with pytest.raises(NotImplementedError):
            await ex.amend_order("42", new_qty=0.1, new_limit_px=60000.0)
