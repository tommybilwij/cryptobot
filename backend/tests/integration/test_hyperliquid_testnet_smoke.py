"""Integration smoke: HyperliquidExchange against real HL testnet.

Marked ``slow``. Requires HYPERLIQUID_WALLET_PRIVATE_KEY env var (testnet wallet).

Order placement is gated behind HYPERLIQUID_SMOKE_PLACE_ORDER=1 — it actually
hits the testnet exchange and creates a real (tiny) resting order. Only enable
when calibrating the EIP-712 signing path.

Run via: cd backend && uv run pytest -m slow tests/integration/test_hyperliquid_testnet_smoke.py -v
"""

from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

from app.backtest.orders import Order
from app.exchanges.hyperliquid import HyperliquidExchange
from app.exchanges.types import Balance
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.slow
@pytest.mark.asyncio
async def test_hyperliquid_testnet_fetch_balance() -> None:
    key = os.environ.get("HYPERLIQUID_WALLET_PRIVATE_KEY")
    if not key:
        pytest.skip("requires HYPERLIQUID_WALLET_PRIVATE_KEY env var")

    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = HyperliquidExchange(
            fetcher=fetcher,
            params=_params(),
            wallet_private_key=key,
            base_url="https://api.hyperliquid-testnet.xyz",
        )
        balance = await ex.fetch_balance("USDC")
    assert isinstance(balance, Balance)
    assert balance.venue == "hyperliquid"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_hyperliquid_testnet_fetch_positions() -> None:
    key = os.environ.get("HYPERLIQUID_WALLET_PRIVATE_KEY")
    if not key:
        pytest.skip("requires HYPERLIQUID_WALLET_PRIVATE_KEY env var")

    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = HyperliquidExchange(
            fetcher=fetcher,
            params=_params(),
            wallet_private_key=key,
            base_url="https://api.hyperliquid-testnet.xyz",
        )
        positions = await ex.fetch_positions()
    assert isinstance(positions, tuple)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_hyperliquid_testnet_place_tiny_order_calibrates_signing() -> None:
    """Validates EIP-712 signing against the real HL testnet.

    Opt-in via HYPERLIQUID_SMOKE_PLACE_ORDER=1 — places a tiny resting limit far
    from market so it never fills. If HL rejects the signature, the test fails
    and the adapter's `_sign_l1_action` formula needs calibration.
    """
    key = os.environ.get("HYPERLIQUID_WALLET_PRIVATE_KEY")
    if not key:
        pytest.skip("requires HYPERLIQUID_WALLET_PRIVATE_KEY env var")
    if os.environ.get("HYPERLIQUID_SMOKE_PLACE_ORDER") != "1":
        pytest.skip("set HYPERLIQUID_SMOKE_PLACE_ORDER=1 to enable order placement")

    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = HyperliquidExchange(
            fetcher=fetcher,
            params=_params(),
            wallet_private_key=key,
            base_url="https://api.hyperliquid-testnet.xyz",
        )
        # Tiny limit far below market so it rests, not fills
        order = Order(
            venue="hyperliquid",
            symbol="BTC",
            product="perp",
            side="buy",
            qty_base=0.001,
            order_type="limit",
            limit_px=1000.0,
        )
        receipt = await ex.place_order(order)
        # If we get here, HL accepted the signature
        assert receipt.order_id
        # Best-effort cancel
        await ex.cancel_order(receipt.order_id)
