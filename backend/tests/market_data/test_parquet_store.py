"""Tests for ParquetStore — write-side partition layout."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from app.market_data.parquet_store import DataType, ParquetStore


@pytest.fixture
def store(tmp_path: Path) -> ParquetStore:
    return ParquetStore(root=tmp_path)


def _sample_klines() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts_ms": [1714521600000, 1714521660000, 1714521720000],
            "open": [60000.0, 60010.0, 60020.0],
            "high": [60015.0, 60025.0, 60030.0],
            "low": [59995.0, 60005.0, 60015.0],
            "close": [60010.0, 60020.0, 60025.0],
            "volume": [10.5, 11.0, 9.75],
        }
    )


def test_path_format(store: ParquetStore) -> None:
    p = store.path("binance", "BTCUSDT", DataType.KLINE_1M, 2026, 4)
    assert p.relative_to(store.root) == Path("binance/BTCUSDT/kline_1m/2026/04.parquet")


def test_write_klines_creates_partition(store: ParquetStore) -> None:
    df = _sample_klines()
    store.write_klines("binance", "BTCUSDT", df, year=2026, month=4)
    p = store.path("binance", "BTCUSDT", DataType.KLINE_1M, 2026, 4)
    assert p.exists()
    read_back = pl.read_parquet(p)
    assert read_back.height == 3
    assert "ts_ms" in read_back.columns


def test_write_klines_overwrites_existing(store: ParquetStore) -> None:
    df1 = _sample_klines()
    df2 = _sample_klines().with_columns(pl.col("close") * 2)
    store.write_klines("binance", "BTCUSDT", df1, year=2026, month=4)
    store.write_klines("binance", "BTCUSDT", df2, year=2026, month=4)
    p = store.path("binance", "BTCUSDT", DataType.KLINE_1M, 2026, 4)
    read_back = pl.read_parquet(p)
    assert read_back["close"].to_list() == [120020.0, 120040.0, 120050.0]


def test_partition_glob(store: ParquetStore) -> None:
    glob = store.glob("binance", "BTCUSDT", DataType.KLINE_1M)
    assert glob == str(store.root / "binance/BTCUSDT/kline_1m/**/*.parquet")
