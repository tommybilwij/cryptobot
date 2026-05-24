"""Tests for Order + Fill dataclasses."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.backtest.orders import Fill, Order


def test_order_is_frozen() -> None:
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="market",
    )
    with pytest.raises(FrozenInstanceError):
        order.qty_base = 99.0  # type: ignore[misc]


def test_order_limit_carries_limit_px() -> None:
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="limit",
        limit_px=59000.0,
    )
    assert order.limit_px == 59000.0


def test_market_order_has_no_limit_px() -> None:
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="sell",
        qty_base=0.1,
        order_type="market",
    )
    assert order.limit_px is None


def test_fill_records_fee_and_price() -> None:
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="market",
    )
    fill = Fill(ts_ms=1714521600000, order=order, fill_px=60030.0, fee_quote=6.0)
    assert fill.fill_px == 60030.0
    assert fill.fee_quote == 6.0


def test_fill_qty_base_signed_buy_positive() -> None:
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.5,
        order_type="market",
    )
    fill = Fill(ts_ms=0, order=order, fill_px=60000.0, fee_quote=0.0)
    assert fill.qty_base_signed == 0.5


def test_fill_qty_base_signed_sell_negative() -> None:
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="sell",
        qty_base=0.5,
        order_type="market",
    )
    fill = Fill(ts_ms=0, order=order, fill_px=60000.0, fee_quote=0.0)
    assert fill.qty_base_signed == -0.5
