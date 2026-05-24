"""Tests for backtest runner — high-level entry that returns BacktestRunResult + metrics."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from app.backtest.runner import RunOptions, run_backtest
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy
from app.market_data.parquet_store import ParquetStore
from app.profile.params import ProfileParams


def test_runner_returns_metrics(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
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

    params = ProfileParams(profile={})
    strategy = BuyAndHoldStrategy(venue="binance", symbol="BTCUSDT")
    opts = RunOptions(
        venue="binance",
        symbols=["BTCUSDT"],
        products=["spot"],
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 1, 0, 2, tzinfo=UTC),
    )
    result = run_backtest(
        parquet_root=tmp_path,
        strategy=strategy,
        params=params,
        options=opts,
    )
    assert result.metrics.num_trades >= 1
    assert result.equity_curve.height == 3
