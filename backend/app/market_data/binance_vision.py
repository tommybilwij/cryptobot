"""Binance Vision archive downloader.

Public archive at https://data.binance.vision/. No API key required.
Each calendar month is one ZIPped CSV; we download, unzip in-memory, and
parse into the canonical Polars schema.
"""

from __future__ import annotations

import io
import zipfile

import polars as pl

from app.market_data._http import RetryingFetcher

BASE_URL = "https://data.binance.vision"

_KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]


class BinanceVisionClient:
    """One instance is reusable across many fetches."""

    name = "binance"

    def __init__(self, *, fetcher: RetryingFetcher) -> None:
        self._fetcher = fetcher

    def _kline_url(self, symbol: str, year: int, month: int) -> str:
        return (
            f"{BASE_URL}/data/spot/monthly/klines/{symbol}/1m/"
            f"{symbol}-1m-{year:04d}-{month:02d}.zip"
        )

    def _funding_url(self, symbol: str, year: int, month: int) -> str:
        return (
            f"{BASE_URL}/data/futures/um/monthly/fundingRate/{symbol}/"
            f"{symbol}-fundingRate-{year:04d}-{month:02d}.zip"
        )

    def _oi_url(self, symbol: str, year: int, month: int) -> str:
        return (
            f"{BASE_URL}/data/futures/um/monthly/metrics/{symbol}/"
            f"{symbol}-metrics-{year:04d}-{month:02d}.zip"
        )

    async def fetch_klines_1m(self, symbol: str, year: int, month: int) -> pl.DataFrame:
        url = self._kline_url(symbol, year, month)
        raw = await self._fetcher.get_bytes(url)
        csv_bytes = _unzip_single(raw)
        df = pl.read_csv(
            csv_bytes,
            has_header=False,
            new_columns=_KLINE_COLUMNS,
            schema_overrides={
                "open_time": pl.Int64,
                "close_time": pl.Int64,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
            },
        )
        return df.select(
            pl.col("open_time").alias("ts_ms"),
            pl.col("open"),
            pl.col("high"),
            pl.col("low"),
            pl.col("close"),
            pl.col("volume"),
        )

    async def fetch_funding_rates(self, symbol: str, year: int, month: int) -> pl.DataFrame:
        url = self._funding_url(symbol, year, month)
        raw = await self._fetcher.get_bytes(url)
        csv_bytes = _unzip_single(raw)
        df = pl.read_csv(
            csv_bytes,
            has_header=True,
            schema_overrides={
                "calc_time": pl.Int64,
                "last_funding_rate": pl.Float64,
            },
        )
        return df.select(
            pl.col("calc_time").alias("ts_ms"),
            # Binance archive only has the realized rate; predicted=realized for historicals
            pl.col("last_funding_rate").alias("predicted"),
            pl.col("last_funding_rate").alias("realized"),
        )

    async def fetch_open_interest(self, symbol: str, year: int, month: int) -> pl.DataFrame:
        url = self._oi_url(symbol, year, month)
        raw = await self._fetcher.get_bytes(url)
        csv_bytes = _unzip_single(raw)
        df = pl.read_csv(csv_bytes, has_header=True, try_parse_dates=True)
        return df.select(
            (pl.col("create_time").dt.timestamp("ms")).alias("ts_ms"),
            pl.col("sum_open_interest").cast(pl.Float64).alias("oi_base"),
            pl.col("sum_open_interest_value").cast(pl.Float64).alias("oi_quote"),
        )


def _unzip_single(raw: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise RuntimeError(f"expected single CSV in zip, got {names}")
        return zf.read(names[0])
