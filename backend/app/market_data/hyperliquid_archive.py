"""Hyperliquid archive downloader — aggregates trades to 1m klines."""

from __future__ import annotations

import gzip
import io

import polars as pl

from app.market_data._http import RetryingFetcher

BASE_URL = "https://hyperliquid-archive.s3.eu-central-1.amazonaws.com"

_MS_PER_MINUTE = 60_000


class HyperliquidArchiveClient:
    """One instance is reusable across many fetches."""

    name = "hyperliquid"

    def __init__(self, *, fetcher: RetryingFetcher) -> None:
        self._fetcher = fetcher

    def _trades_url(self, coin: str, year: int, month: int) -> str:
        return f"{BASE_URL}/trades/{coin}/{year:04d}-{month:02d}.jsonl.gz"

    async def fetch_klines_1m(self, symbol: str, year: int, month: int) -> pl.DataFrame:
        url = self._trades_url(symbol, year, month)
        raw = await self._fetcher.get_bytes(url)
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            jsonl = gz.read().decode()
        trades = pl.read_ndjson(io.BytesIO(jsonl.encode()))
        # Aggregate to 1m OHLCV
        return (
            trades.with_columns(
                (pl.col("time") // _MS_PER_MINUTE * _MS_PER_MINUTE).alias("ts_ms"),
                pl.col("px").cast(pl.Float64),
                pl.col("sz").cast(pl.Float64),
            )
            .group_by("ts_ms")
            .agg(
                pl.col("px").first().alias("open"),
                pl.col("px").max().alias("high"),
                pl.col("px").min().alias("low"),
                pl.col("px").last().alias("close"),
                pl.col("sz").sum().alias("volume"),
            )
            .sort("ts_ms")
        )
