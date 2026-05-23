"""Tests for DataPipelineService."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from app.market_data.parquet_store import DataType, ParquetStore
from app.services.data_pipeline import DataPipelineService


class _FakeBinance:
    name = "binance"

    async def fetch_klines_1m(self, symbol: str, year: int, month: int) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "ts_ms": [1714521600000, 1714521660000],
                "open": [60000.0, 60010.0],
                "high": [60015.0, 60025.0],
                "low": [59995.0, 60005.0],
                "close": [60010.0, 60020.0],
                "volume": [10.5, 11.0],
            }
        )


@pytest.mark.asyncio
async def test_refresh_writes_partition(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
    svc = DataPipelineService(store=store, sources={"binance": _FakeBinance()})
    await svc.refresh_klines_1m("binance", "BTCUSDT", year=2026, month=4)
    p = store.path("binance", "BTCUSDT", DataType.KLINE_1M, 2026, 4)
    assert p.exists()
    df = pl.read_parquet(p)
    assert df.height == 2
