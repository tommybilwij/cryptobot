"""Tests for exchange dataclasses."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.exchanges.types import Balance, ExchangePosition, OrderReceipt, OrderStatus


def test_balance_is_frozen() -> None:
    b = Balance(venue="binance", quote_currency="USDC", free=10000.0, locked=0.0)
    with pytest.raises(FrozenInstanceError):
        b.free = 99.0  # type: ignore[misc]


def test_exchange_position_signed_qty() -> None:
    p = ExchangePosition(
        venue="binance", symbol="BTCUSDT", product="perp",
        qty_base=-0.5, avg_entry_px=60000.0, mark_px=60050.0,
        unrealized_pnl_quote=-25.0,
    )
    assert p.qty_base < 0


def test_order_receipt_carries_id() -> None:
    r = OrderReceipt(order_id="abc-1", venue="binance", symbol="BTCUSDT", submitted_ts_ms=1)
    assert r.order_id == "abc-1"


def test_order_status_filled_carries_fill_px() -> None:
    s = OrderStatus(
        order_id="abc-1", status="filled", fill_px=60010.0,
        filled_qty_base=0.1, fee_quote=0.6, raw={},
    )
    assert s.status == "filled"
    assert s.fill_px == 60010.0


def test_order_status_pending_has_no_fill_px() -> None:
    s = OrderStatus(
        order_id="abc-1", status="pending", fill_px=None,
        filled_qty_base=0.0, fee_quote=0.0, raw={},
    )
    assert s.fill_px is None
