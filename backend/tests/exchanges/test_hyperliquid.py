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
        assert (
            b'"type":"clearinghouseState"' in body
            or b'"type": "clearinghouseState"' in body
        )
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
    assert isinstance(payload["signature"], str)
    assert len(payload["signature"]) > 0
