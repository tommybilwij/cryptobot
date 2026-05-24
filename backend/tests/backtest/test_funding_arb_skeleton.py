"""Tests for FundingArbSkeleton — hedge-pair + funding engine validator."""

from __future__ import annotations

from app.backtest.state import Bar, MarketSnapshot, MarketState, Position
from app.backtest.strategies.funding_arb_skeleton import FundingArbSkeleton
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def _state(positions: tuple[Position, ...] = (), cash: float = 10_000.0) -> MarketState:
    spot_bar = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="spot",
        open=60000.0, high=60050.0, low=59950.0, close=60010.0, volume=10.0,
    )
    perp_bar = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="perp",
        open=60000.0, high=60050.0, low=59950.0, close=60010.0, volume=10.0,
    )
    return MarketState(
        snapshot=MarketSnapshot(
            ts_ms=1,
            bars={
                ("binance", "BTCUSDT", "spot"): spot_bar,
                ("binance", "BTCUSDT", "perp"): perp_bar,
            },
        ),
        positions=positions,
        cash_quote=cash,
    )


def test_emits_hedge_pair_when_no_position() -> None:
    s = FundingArbSkeleton(venue="binance", symbol="BTCUSDT")
    orders = s.evaluate(_state(), _params())
    assert len(orders) == 2
    spots = [o for o in orders if o.product == "spot"]
    perps = [o for o in orders if o.product == "perp"]
    assert len(spots) == 1
    assert len(perps) == 1
    assert spots[0].side == "buy"
    assert perps[0].side == "sell"
    # qty matches (delta neutral)
    assert spots[0].qty_base == perps[0].qty_base


def test_emits_nothing_when_already_hedged() -> None:
    s = FundingArbSkeleton(venue="binance", symbol="BTCUSDT")
    long_spot = Position(venue="binance", symbol="BTCUSDT", product="spot", qty_base=0.08, avg_entry_px=60000.0)
    short_perp = Position(venue="binance", symbol="BTCUSDT", product="perp", qty_base=-0.08, avg_entry_px=60000.0)
    orders = s.evaluate(_state(positions=(long_spot, short_perp)), _params())
    assert orders == []
