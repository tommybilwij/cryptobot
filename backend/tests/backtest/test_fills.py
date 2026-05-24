"""Tests for FillSimulator — constant-bps slippage + fees from profile."""

from __future__ import annotations

import pytest

from app.backtest.fills import FillSimulator, InsufficientCashError
from app.backtest.orders import Order
from app.backtest.state import Bar, MarketSnapshot
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def _snap(
    close: float = 60000.0,
    venue: str = "binance",
    symbol: str = "BTCUSDT",
    product: str = "spot",
) -> MarketSnapshot:
    bar = Bar(
        ts_ms=1, venue=venue, symbol=symbol, product=product,  # type: ignore[arg-type]
        open=close, high=close, low=close, close=close, volume=100.0,
    )
    return MarketSnapshot(ts_ms=1, bars={(venue, symbol, product): bar})  # type: ignore[dict-item]


def test_market_buy_pays_up_with_slippage() -> None:
    sim = FillSimulator(params=_params())
    order = Order(venue="binance", symbol="BTCUSDT", product="spot", side="buy", qty_base=0.1, order_type="market")
    fills, cash_after = sim.fill([order], _snap(60000.0), cash=10_000.0)
    # 5 bps slippage → fill at 60030
    assert fills[0].fill_px == pytest.approx(60030.0)
    # Fee: 10 bps of notional = 10 / 10_000 * (0.1 * 60030) = 6.003
    assert fills[0].fee_quote == pytest.approx(6.003, rel=1e-4)


def test_market_sell_gets_discounted_by_slippage() -> None:
    sim = FillSimulator(params=_params())
    order = Order(venue="binance", symbol="BTCUSDT", product="spot", side="sell", qty_base=0.1, order_type="market")
    fills, _ = sim.fill([order], _snap(60000.0), cash=10_000.0)
    # 5 bps slippage on sell → 60000 * (1 - 0.0005) = 59970
    assert fills[0].fill_px == pytest.approx(59970.0)


def test_buy_with_insufficient_cash_raises() -> None:
    sim = FillSimulator(params=_params())
    order = Order(venue="binance", symbol="BTCUSDT", product="spot", side="buy", qty_base=10.0, order_type="market")
    with pytest.raises(InsufficientCashError):
        sim.fill([order], _snap(60000.0), cash=1000.0)


def test_limit_order_fills_if_touched_in_bar() -> None:
    sim = FillSimulator(params=_params())
    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot", side="buy",
        qty_base=0.1, order_type="limit", limit_px=59500.0,
    )
    bar = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="spot",
        open=60000.0, high=60100.0, low=59400.0, close=60050.0, volume=10.0,
    )
    snap = MarketSnapshot(ts_ms=1, bars={("binance", "BTCUSDT", "spot"): bar})
    fills, _ = sim.fill([order], snap, cash=10_000.0)
    assert fills[0].fill_px == 59500.0


def test_limit_order_dropped_if_not_touched() -> None:
    sim = FillSimulator(params=_params())
    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot", side="buy",
        qty_base=0.1, order_type="limit", limit_px=58000.0,
    )
    bar = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="spot",
        open=60000.0, high=60100.0, low=59400.0, close=60050.0, volume=10.0,
    )
    snap = MarketSnapshot(ts_ms=1, bars={("binance", "BTCUSDT", "spot"): bar})
    fills, _ = sim.fill([order], snap, cash=10_000.0)
    assert fills == []
