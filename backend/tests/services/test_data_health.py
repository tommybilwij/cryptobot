"""Tests for DataHealthService."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.parquet_store import ParquetStore
from app.services.data_health import DataHealthService


@pytest.mark.asyncio
async def test_detect_gaps_no_gaps(tmp_path: Path, db_session: AsyncSession) -> None:
    store = ParquetStore(root=tmp_path)
    # 3 consecutive 1-minute klines
    df = pl.DataFrame(
        {
            "ts_ms": [1714521600000, 1714521660000, 1714521720000],
            "open": [1.0, 1.0, 1.0],
            "high": [1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0],
            "close": [1.0, 1.0, 1.0],
            "volume": [1.0, 1.0, 1.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=2026, month=4)

    svc = DataHealthService(session=db_session, parquet_root=tmp_path)
    gaps = svc.detect_kline_gaps("binance", "BTCUSDT", year=2026, month=4)
    assert gaps == []


@pytest.mark.asyncio
async def test_detect_gaps_finds_missing_minute(
    tmp_path: Path, db_session: AsyncSession
) -> None:
    store = ParquetStore(root=tmp_path)
    # Minute 1714521660000 is missing (gap between :600 and :720)
    df = pl.DataFrame(
        {
            "ts_ms": [1714521600000, 1714521720000],
            "open": [1.0, 1.0],
            "high": [1.0, 1.0],
            "low": [1.0, 1.0],
            "close": [1.0, 1.0],
            "volume": [1.0, 1.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=2026, month=4)

    svc = DataHealthService(session=db_session, parquet_root=tmp_path)
    gaps = svc.detect_kline_gaps("binance", "BTCUSDT", year=2026, month=4)
    assert len(gaps) == 1
    assert gaps[0] == (1714521660000, 1714521660000)
