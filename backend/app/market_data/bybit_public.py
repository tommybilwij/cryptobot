"""Bybit public archive downloader.

Public archive at https://public.bybit.com/. No API key. Files are .csv.gz.
Bybit's timestamps are in SECONDS (not ms like Binance) — we convert.
"""

from __future__ import annotations

import gzip
import io

import polars as pl

from app.market_data._http import RetryingFetcher

BASE_URL = "https://public.bybit.com"

_MS_PER_S = 1000


class BybitPublicClient:
    """One instance is reusable across many fetches."""

    name = "bybit"

    def __init__(self, *, fetcher: RetryingFetcher) -> None:
        self._fetcher = fetcher

    def _kline_url(self, symbol: str, year: int, month: int) -> str:
        return (
            f"{BASE_URL}/spot_index_price_kline/{symbol}/1m/"
            f"{symbol}-{year:04d}-{month:02d}.csv.gz"
        )

    async def fetch_klines_1m(self, symbol: str, year: int, month: int) -> pl.DataFrame:
        url = self._kline_url(symbol, year, month)
        raw = await self._fetcher.get_bytes(url)
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            csv_bytes = gz.read()
        df = pl.read_csv(csv_bytes, has_header=True)
        return df.select(
            (pl.col("start_at").cast(pl.Int64) * _MS_PER_S).alias("ts_ms"),
            pl.col("open").cast(pl.Float64),
            pl.col("high").cast(pl.Float64),
            pl.col("low").cast(pl.Float64),
            pl.col("close").cast(pl.Float64),
            pl.col("volume").cast(pl.Float64),
        )
