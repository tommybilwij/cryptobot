"""Integration: real-network smoke against Binance Vision.

Marked ``slow`` so it skips by default; opt in with ``pytest -m slow``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.market_data._http import RetryingFetcher
from app.market_data.binance_vision import BinanceVisionClient
from app.market_data.parquet_store import DataType, ParquetStore

_MIN_EXPECTED_ROWS = 44_000  # Jan 2024 ~ 31*24*60 = 44_640 minutes


@pytest.mark.slow
@pytest.mark.asyncio
async def test_real_binance_vision_btcusdt_kline_2024_01(tmp_path: Path) -> None:
    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http)
        client = BinanceVisionClient(fetcher=fetcher)
        df = await client.fetch_klines_1m("BTCUSDT", 2024, 1)

    assert df.height >= _MIN_EXPECTED_ROWS
    assert df.columns == ["ts_ms", "open", "high", "low", "close", "volume"]

    store = ParquetStore(root=tmp_path)
    store.write_klines("binance", "BTCUSDT", df, year=2024, month=1)
    written = store.path("binance", "BTCUSDT", DataType.KLINE_1M, 2024, 1)
    assert written.exists()
    assert written.suffix == ".parquet"
