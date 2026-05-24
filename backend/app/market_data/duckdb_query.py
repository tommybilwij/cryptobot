"""DuckDBQuery — read-side API over the Parquet store.

DuckDB scans Parquet files via globbing + partition pruning. Each call opens a
fresh in-process connection (DuckDB sessions are not designed for long-lived
shared mutable state); cold-start overhead is ~5ms which is negligible for
backtest workloads.

Partition pruning is path-driven: we enumerate ``{year}/{month}.parquet`` files
under the (exchange, symbol, type) subtree and pass DuckDB only the files whose
(year, month) overlaps the requested ``[start, end]`` window. This keeps the
read footprint tight even when a symbol has years of history on disk.

Returns Polars frames everywhere — pandas is explicitly NOT used in
``backend/app/market_data/`` (per Phase 3 architectural choice).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
import polars as pl

from app.market_data.parquet_store import DataType


class DuckDBQuery:
    """Read-side query helper. Stateless beyond the Parquet root path."""

    def __init__(self, parquet_root: Path) -> None:
        self.parquet_root = parquet_root

    def klines(
        self,
        exchange: str,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        return self._query_partitioned(exchange, symbol, DataType.KLINE_1M, start, end)

    def funding_rates(
        self,
        exchange: str,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        return self._query_partitioned(exchange, symbol, DataType.FUNDING_RATE, start, end)

    def open_interest(
        self,
        exchange: str,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        return self._query_partitioned(exchange, symbol, DataType.OPEN_INTEREST, start, end)

    def _query_partitioned(
        self,
        exchange: str,
        symbol: str,
        data_type: DataType,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        files = self._select_partition_files(exchange, symbol, data_type, start, end)
        if not files:
            return pl.DataFrame()

        conn = duckdb.connect(":memory:")
        # DuckDB read_parquet accepts a Python list literal of file paths.
        file_list = "[" + ", ".join(f"'{p}'" for p in files) + "]"
        query = f"SELECT * FROM read_parquet({file_list}) ORDER BY ts_ms"
        result = conn.execute(query).pl()
        conn.close()
        return result

    def _select_partition_files(
        self,
        exchange: str,
        symbol: str,
        data_type: DataType,
        start: datetime,
        end: datetime,
    ) -> list[Path]:
        """Return ``{year}/{month}.parquet`` files overlapping ``[start, end]``."""
        root = self.parquet_root / exchange / symbol / data_type.value
        if not root.exists():
            return []
        start_key = (start.year, start.month)
        end_key = (end.year, end.month)
        out: list[Path] = []
        for p in root.glob("*/*.parquet"):
            try:
                year = int(p.parent.name)
                month = int(p.stem)
            except ValueError:
                continue
            if start_key <= (year, month) <= end_key:
                out.append(p)
        return sorted(out)
