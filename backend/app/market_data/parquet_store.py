"""ParquetStore — write-side partition layout for historical data.

Partition scheme: ``{root}/{exchange}/{symbol}/{type}/{yyyy}/{mm}.parquet``.

Designed for query patterns that scan one symbol within a date range — DuckDB
prunes by directory and skips months outside the range. Files are rewritten
in-place when a backfill re-downloads them; consumers should not assume
content stability across writes.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import polars as pl


class DataType(StrEnum):
    KLINE_1M = "kline_1m"
    TRADES = "trades"
    FUNDING_RATE = "funding_rate"
    OPEN_INTEREST = "open_interest"


class ParquetStore:
    """Owns the write-side path layout. Read side lives in DuckDBQuery."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(
        self,
        exchange: str,
        symbol: str,
        data_type: DataType,
        year: int,
        month: int,
    ) -> Path:
        return (
            self.root
            / exchange
            / symbol
            / data_type.value
            / f"{year:04d}"
            / f"{month:02d}.parquet"
        )

    def glob(self, exchange: str, symbol: str, data_type: DataType) -> str:
        """Glob expression matching all partitions for one (exchange, symbol, type)."""
        return str(self.root / exchange / symbol / data_type.value / "**/*.parquet")

    def write_klines(
        self,
        exchange: str,
        symbol: str,
        df: pl.DataFrame,
        *,
        year: int,
        month: int,
    ) -> Path:
        p = self.path(exchange, symbol, DataType.KLINE_1M, year, month)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(p, compression="zstd")
        return p

    def write_funding(
        self,
        exchange: str,
        symbol: str,
        df: pl.DataFrame,
        *,
        year: int,
        month: int,
    ) -> Path:
        p = self.path(exchange, symbol, DataType.FUNDING_RATE, year, month)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(p, compression="zstd")
        return p

    def write_open_interest(
        self,
        exchange: str,
        symbol: str,
        df: pl.DataFrame,
        *,
        year: int,
        month: int,
    ) -> Path:
        p = self.path(exchange, symbol, DataType.OPEN_INTEREST, year, month)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(p, compression="zstd")
        return p
