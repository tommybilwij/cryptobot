"""Tests for BuyAndHoldStrategy — engine validator."""

from __future__ import annotations

from app.backtest.state import Bar, MarketSnapshot, MarketState, Position
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def _state(positions: tuple[Position, ...] = (), cash: float = 10_000.0) -> MarketState:
    bar = Bar(
        ts_ms=1,
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        open=60000.0,
        high=60050.0,
        low=59950.0,
        close=60010.0,
        volume=10.0,
    )
    return MarketState(
        snapshot=MarketSnapshot(ts_ms=1, bars={("binance", "BTCUSDT", "spot"): bar}),
        positions=positions,
        cash_quote=cash,
    )


def test_emits_buy_when_no_position() -> None:
    s = BuyAndHoldStrategy(venue="binance", symbol="BTCUSDT")
    orders = s.evaluate(_state(), _params())
    assert len(orders) == 1
    assert orders[0].side == "buy"
    assert orders[0].symbol == "BTCUSDT"
    assert orders[0].order_type == "market"


def test_emits_nothing_when_already_long() -> None:
    s = BuyAndHoldStrategy(venue="binance", symbol="BTCUSDT")
    long = Position(
        venue="binance", symbol="BTCUSDT", product="spot", qty_base=0.16, avg_entry_px=60000.0
    )
    orders = s.evaluate(_state(positions=(long,)), _params())
    assert orders == []
