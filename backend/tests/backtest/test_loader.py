"""Tests for backtest data loader — Parquet → MarketSnapshot generator."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from app.backtest.loader import BacktestDataError, BacktestLoader
from app.market_data.parquet_store import ParquetStore


def _write_klines(store: ParquetStore, year: int, month: int) -> int:
    # Three consecutive 1m bars starting at 2024-01-01 00:00 UTC
    base = 1704067200000
    df = pl.DataFrame(
        {
            "ts_ms": [base, base + 60_000, base + 120_000],
            "open": [60000.0, 60100.0, 60200.0],
            "high": [60050.0, 60150.0, 60250.0],
            "low": [59950.0, 60050.0, 60150.0],
            "close": [60010.0, 60110.0, 60210.0],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=year, month=month)
    return base


def test_loader_iterates_snapshots(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
    _write_klines(store, 2024, 1)
    loader = BacktestLoader(parquet_root=tmp_path)
    start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 2, 0, tzinfo=UTC)
    snaps = list(
        loader.iter_snapshots(
            venue="binance",
            symbols=["BTCUSDT"],
            products=["spot"],
            start=start,
            end=end,
        )
    )
    assert len(snaps) == 3
    assert snaps[0].bars[("binance", "BTCUSDT", "spot")].close == 60010.0
    assert snaps[2].bars[("binance", "BTCUSDT", "spot")].close == 60210.0


def test_loader_raises_when_no_data(tmp_path: Path) -> None:
    loader = BacktestLoader(parquet_root=tmp_path)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 31, tzinfo=UTC)
    with pytest.raises(BacktestDataError):
        list(
            loader.iter_snapshots(
                venue="binance",
                symbols=["BTCUSDT"],
                products=["spot"],
                start=start,
                end=end,
            )
        )


def test_loader_populates_funding_rates(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
    base = 1704067200000
    # klines
    kline_df = pl.DataFrame(
        {
            "ts_ms": [base, base + 60_000, base + 120_000],
            "open": [60000.0, 60100.0, 60200.0],
            "high": [60050.0, 60150.0, 60250.0],
            "low": [59950.0, 60050.0, 60150.0],
            "close": [60010.0, 60110.0, 60210.0],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", kline_df, year=2024, month=1)
    # funding (one rate at base + 120_000)
    funding_df = pl.DataFrame(
        {
            "ts_ms": [base + 120_000],
            "predicted": [0.0002],
            "realized": [0.00015],
        }
    )
    store.write_funding("binance", "BTCUSDT", funding_df, year=2024, month=1)

    loader = BacktestLoader(parquet_root=tmp_path)
    start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 2, 0, tzinfo=UTC)
    snaps = list(
        loader.iter_snapshots(
            venue="binance",
            symbols=["BTCUSDT"],
            products=["spot"],
            start=start,
            end=end,
        )
    )
    # First 2 bars: no funding event yet, expect empty dict
    assert snaps[0].funding_rates == {}
    assert snaps[1].funding_rates == {}
    # Third bar: funding event at this ts
    assert snaps[2].funding_rates == {("binance", "BTCUSDT"): 0.00015}
