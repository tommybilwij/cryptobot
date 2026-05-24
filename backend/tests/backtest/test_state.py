"""Tests for backtest state dataclasses."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.backtest.state import Bar, MarketSnapshot, MarketState, Position


def test_bar_is_frozen() -> None:
    bar = Bar(
        ts_ms=1714521600000,
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        open=60000.0,
        high=60015.0,
        low=59995.0,
        close=60010.0,
        volume=10.5,
    )
    with pytest.raises(FrozenInstanceError):
        bar.close = 99.0  # type: ignore[misc]


def test_market_snapshot_lookup_by_key() -> None:
    bar = Bar(
        ts_ms=1714521600000,
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        open=60000.0,
        high=60015.0,
        low=59995.0,
        close=60010.0,
        volume=10.5,
    )
    snap = MarketSnapshot(ts_ms=1714521600000, bars={("binance", "BTCUSDT", "spot"): bar})
    assert snap.bars[("binance", "BTCUSDT", "spot")].close == 60010.0


def test_position_signed_qty() -> None:
    long = Position(venue="binance", symbol="BTCUSDT", product="spot", qty_base=0.5, avg_entry_px=60000.0)
    short = Position(venue="binance", symbol="BTCUSDT", product="perp", qty_base=-0.5, avg_entry_px=60010.0)
    assert long.qty_base > 0
    assert short.qty_base < 0


def test_market_state_positions_are_tuple() -> None:
    state = MarketState(
        snapshot=MarketSnapshot(ts_ms=0, bars={}),
        positions=(),
        cash_quote=10000.0,
    )
    assert isinstance(state.positions, tuple)
