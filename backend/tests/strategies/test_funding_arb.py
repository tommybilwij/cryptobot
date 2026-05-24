"""Tests for FundingArbStrategy — Phase 6 real strategy."""

from __future__ import annotations

from app.backtest.state import Bar, MarketSnapshot, MarketState, Position
from app.profile.params import ProfileParams
from app.strategies.funding_arb import FundingArbStrategy


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def _snap(funding: float = 0.0) -> MarketSnapshot:
    spot = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="spot",
        open=60000.0, high=60010.0, low=59990.0, close=60000.0, volume=10.0,
    )
    perp = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="perp",
        open=60000.0, high=60010.0, low=59990.0, close=60000.0, volume=10.0,
    )
    return MarketSnapshot(
        ts_ms=1,
        bars={
            ("binance", "BTCUSDT", "spot"): spot,
            ("binance", "BTCUSDT", "perp"): perp,
        },
        funding_rates={("binance", "BTCUSDT"): funding},
    )


def _state(
    positions: tuple[Position, ...] = (),
    cash: float = 10_000.0,
    funding: float = 0.0,
) -> MarketState:
    return MarketState(
        snapshot=_snap(funding), positions=positions, cash_quote=cash
    )


def test_flat_under_threshold_no_orders() -> None:
    # entry threshold default 8.0 bps; here 7 bps → no entry
    s = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    orders = s.evaluate(_state(funding=0.0007), _params())
    assert orders == []


def test_no_funding_data_for_venue_no_orders() -> None:
    s = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    state = MarketState(
        snapshot=MarketSnapshot(
            ts_ms=1,
            bars={
                ("binance", "BTCUSDT", "spot"): Bar(
                    ts_ms=1, venue="binance", symbol="BTCUSDT", product="spot",
                    open=60000.0, high=60000.0, low=60000.0, close=60000.0,
                    volume=1.0,
                ),
                ("binance", "BTCUSDT", "perp"): Bar(
                    ts_ms=1, venue="binance", symbol="BTCUSDT", product="perp",
                    open=60000.0, high=60000.0, low=60000.0, close=60000.0,
                    volume=1.0,
                ),
            },
            funding_rates={},
        ),
        positions=(),
        cash_quote=10_000.0,
    )
    orders = s.evaluate(state, _params())
    assert orders == []
