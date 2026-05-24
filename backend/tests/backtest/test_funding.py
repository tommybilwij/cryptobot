"""Tests for FundingLedger — applies per-venue funding payments at venue cadence."""

from __future__ import annotations

import polars as pl

from app.backtest.funding import FundingLedger
from app.backtest.state import Position


def _funding_df(events: list[tuple[int, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts_ms": [t for t, _ in events],
            "predicted": [r for _, r in events],
            "realized": [r for _, r in events],
        }
    )


def test_no_perp_position_no_op() -> None:
    ledger = FundingLedger()
    pos_long_spot = Position(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        qty_base=0.5,
        avg_entry_px=60000.0,
    )
    events = ledger.events_for(
        positions=(pos_long_spot,),
        ts_ms=1714521600000,
        funding_data={},
        mark_pxs={},
    )
    assert events == []


def test_short_perp_collects_positive_funding() -> None:
    ledger = FundingLedger()
    short = Position(
        venue="binance",
        symbol="BTCUSDT",
        product="perp",
        qty_base=-0.5,
        avg_entry_px=60000.0,
    )
    df = _funding_df([(1714521600000, 0.0001)])  # 1 bps funding
    events = ledger.events_for(
        positions=(short,),
        ts_ms=1714521600000,
        funding_data={("binance", "BTCUSDT"): df},
        mark_pxs={("binance", "BTCUSDT", "perp"): 60000.0},
    )
    # short 0.5 BTC @ 60000 = 30000 notional (abs); positive funding → short collects
    # payment = -sign(qty) * notional * rate = +1 * 30000 * 0.0001 = +3.0
    assert len(events) == 1
    assert events[0].payment_quote == 3.0


def test_long_perp_pays_positive_funding() -> None:
    ledger = FundingLedger()
    long = Position(
        venue="binance",
        symbol="BTCUSDT",
        product="perp",
        qty_base=0.5,
        avg_entry_px=60000.0,
    )
    df = _funding_df([(1714521600000, 0.0001)])
    events = ledger.events_for(
        positions=(long,),
        ts_ms=1714521600000,
        funding_data={("binance", "BTCUSDT"): df},
        mark_pxs={("binance", "BTCUSDT", "perp"): 60000.0},
    )
    assert events[0].payment_quote == -3.0


def test_no_event_when_ts_not_in_funding_data() -> None:
    ledger = FundingLedger()
    short = Position(
        venue="binance",
        symbol="BTCUSDT",
        product="perp",
        qty_base=-0.5,
        avg_entry_px=60000.0,
    )
    df = _funding_df([(1714521600000, 0.0001)])
    events = ledger.events_for(
        positions=(short,),
        ts_ms=1714521660000,  # one minute later, no funding event here
        funding_data={("binance", "BTCUSDT"): df},
        mark_pxs={("binance", "BTCUSDT", "perp"): 60000.0},
    )
    assert events == []
