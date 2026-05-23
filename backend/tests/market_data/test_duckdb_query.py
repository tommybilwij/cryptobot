"""Tests for DuckDBQuery — read-side over ParquetStore."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from app.market_data.duckdb_query import DuckDBQuery
from app.market_data.parquet_store import ParquetStore


@pytest.fixture
def store_with_data(tmp_path: Path) -> ParquetStore:
    store = ParquetStore(root=tmp_path)
    apr = pl.DataFrame(
        {
            "ts_ms": [1714521600000, 1714521660000, 1714521720000],
            "open": [60000.0, 60010.0, 60020.0],
            "high": [60015.0, 60025.0, 60030.0],
            "low": [59995.0, 60005.0, 60015.0],
            "close": [60010.0, 60020.0, 60025.0],
            "volume": [10.5, 11.0, 9.75],
        }
    )
    may = pl.DataFrame(
        {
            "ts_ms": [1717200000000, 1717200060000],
            "open": [61000.0, 61010.0],
            "high": [61015.0, 61025.0],
            "low": [60995.0, 61005.0],
            "close": [61010.0, 61020.0],
            "volume": [9.0, 8.5],
        }
    )
    store.write_klines("binance", "BTCUSDT", apr, year=2026, month=4)
    store.write_klines("binance", "BTCUSDT", may, year=2026, month=5)
    return store


def test_klines_returns_polars_frame(store_with_data: ParquetStore) -> None:
    q = DuckDBQuery(parquet_root=store_with_data.root)
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 5, 31, tzinfo=UTC)
    df = q.klines("binance", "BTCUSDT", start, end)
    assert isinstance(df, pl.DataFrame)
    assert df.height == 5
    assert df.columns == ["ts_ms", "open", "high", "low", "close", "volume"]


def test_klines_date_filter_prunes_partitions(store_with_data: ParquetStore) -> None:
    q = DuckDBQuery(parquet_root=store_with_data.root)
    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 5, 31, tzinfo=UTC)
    df = q.klines("binance", "BTCUSDT", start, end)
    assert df.height == 2
    assert df["close"].to_list() == [61010.0, 61020.0]


def test_klines_empty_when_no_data(tmp_path: Path) -> None:
    q = DuckDBQuery(parquet_root=tmp_path)
    df = q.klines(
        "binance",
        "BTCUSDT",
        datetime(2026, 4, 1, tzinfo=UTC),
        datetime(2026, 5, 31, tzinfo=UTC),
    )
    assert df.is_empty()
