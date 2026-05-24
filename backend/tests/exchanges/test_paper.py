"""Tests for PaperExchange — in-memory state machine for unit tests + dry-run."""

from __future__ import annotations

import pytest

from app.backtest.orders import Order
from app.exchanges.paper import PaperExchange
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.asyncio
async def test_paper_fetch_balance_starts_at_initial_cash() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    b = await ex.fetch_balance("USDC")
    assert b.free == 10_000.0
    assert b.locked == 0.0


@pytest.mark.asyncio
async def test_paper_place_buy_fills_at_mark_with_slippage() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    ex.set_mark_price("BTCUSDT", "spot", 60000.0)
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="market",
    )
    receipt = await ex.place_order(order)
    assert receipt.order_id
    status = await ex.fetch_order(receipt.order_id)
    assert status.status == "filled"
    # 5 bps slippage on default Binance config → 60030
    assert status.fill_px == pytest.approx(60030.0)
    assert status.filled_qty_base == 0.1
    # 10 bps fee on spot
    assert status.fee_quote == pytest.approx(6.003, rel=1e-4)


@pytest.mark.asyncio
async def test_paper_fill_debits_balance() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    ex.set_mark_price("BTCUSDT", "spot", 60000.0)
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="market",
    )
    await ex.place_order(order)
    b = await ex.fetch_balance("USDC")
    # notional 0.1 * 60030 = 6003 + fee 6.003 = 6009.003
    assert b.free == pytest.approx(10_000.0 - 6009.003, rel=1e-4)


@pytest.mark.asyncio
async def test_paper_fetch_positions_after_buy() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    ex.set_mark_price("BTCUSDT", "spot", 60000.0)
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="market",
    )
    await ex.place_order(order)
    positions = await ex.fetch_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].qty_base == 0.1


@pytest.mark.asyncio
async def test_paper_cancel_pending_is_noop_for_market_fills() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    ex.set_mark_price("BTCUSDT", "spot", 60000.0)
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="market",
    )
    receipt = await ex.place_order(order)
    # Already filled — cancel is no-op
    await ex.cancel_order(receipt.order_id)
    status = await ex.fetch_order(receipt.order_id)
    assert status.status == "filled"


@pytest.mark.asyncio
async def test_paper_fetch_funding_rate_returns_configured_rate() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    ex.set_funding_rate("BTCUSDT", 0.0001)
    rate = await ex.fetch_funding_rate("BTCUSDT")
    assert rate == 0.0001


@pytest.mark.asyncio
async def test_paper_fetch_funding_rate_missing_returns_none() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    rate = await ex.fetch_funding_rate("BTCUSDT")
    assert rate is None
