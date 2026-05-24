"""Tests for backtest Engine — event loop integrating loader + strategy + fills + funding."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from app.backtest.engine import Engine
from app.backtest.loader import BacktestDataError, BacktestLoader
from app.backtest.orders import Order
from app.backtest.state import MarketState
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy
from app.market_data.parquet_store import ParquetStore
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def _write_klines(store: ParquetStore) -> int:
    # Three 1m bars: 60000 → 60100 → 60200
    base = 1704067200000
    df = pl.DataFrame(
        {
            "ts_ms": [base, base + 60_000, base + 120_000],
            "open": [60000.0, 60100.0, 60200.0],
            "high": [60050.0, 60150.0, 60250.0],
            "low": [59950.0, 60050.0, 60150.0],
            "close": [60000.0, 60100.0, 60200.0],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=2024, month=1)
    return base


def test_buy_and_hold_equity_curve_rises_with_price(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
    _write_klines(store)
    loader = BacktestLoader(parquet_root=tmp_path)
    strategy = BuyAndHoldStrategy(venue="binance", symbol="BTCUSDT")
    engine = Engine(loader=loader, strategy=strategy, params=_params())
    start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 2, tzinfo=UTC)
    result = engine.run(
        venue="binance",
        symbols=["BTCUSDT"],
        products=["spot"],
        start=start,
        end=end,
    )

    assert result.equity_curve.height == 3
    equity = result.equity_curve["equity"].to_list()
    assert equity[2] > equity[0]  # price went up 60000 → 60200, equity should rise
    assert result.num_trades == 1  # one buy at tick 1, then holds


def test_engine_raises_on_missing_data(tmp_path: Path) -> None:
    loader = BacktestLoader(parquet_root=tmp_path)
    strategy = BuyAndHoldStrategy(venue="binance", symbol="BTCUSDT")
    engine = Engine(loader=loader, strategy=strategy, params=_params())
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 31, tzinfo=UTC)
    with pytest.raises(BacktestDataError):
        engine.run(
            venue="binance",
            symbols=["BTCUSDT"],
            products=["spot"],
            start=start,
            end=end,
        )


def test_zero_orders_per_tick_produces_flat_curve(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
    _write_klines(store)
    loader = BacktestLoader(parquet_root=tmp_path)

    class NullStrategy:
        name = "null"

        def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
            return []

    params = _params()
    engine = Engine(loader=loader, strategy=NullStrategy(), params=params)
    start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 2, tzinfo=UTC)
    result = engine.run(
        venue="binance",
        symbols=["BTCUSDT"],
        products=["spot"],
        start=start,
        end=end,
    )

    initial = float(params.get("backtest.initial_cash_quote_usdc"))
    assert all(e == initial for e in result.equity_curve["equity"].to_list())
    assert result.num_trades == 0
