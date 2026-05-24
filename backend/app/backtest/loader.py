"""BacktestLoader — streams MarketSnapshot per bar from partitioned Parquet."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import polars as pl

from app.backtest.state import Bar, MarketSnapshot, Product
from app.market_data.duckdb_query import DuckDBQuery


class BacktestDataError(RuntimeError):
    """Raised when the requested backtest window has no underlying data."""


class BacktestLoader:
    """Loads Parquet partitions and yields MarketSnapshot objects bar-by-bar."""

    def __init__(self, *, parquet_root: Path) -> None:
        self._root = parquet_root
        self._query = DuckDBQuery(parquet_root=parquet_root)

    def iter_snapshots(
        self,
        *,
        venue: str,
        symbols: list[str],
        products: list[Product],
        start: datetime,
        end: datetime,
    ) -> Iterator[MarketSnapshot]:
        frames: dict[tuple[str, str, Product], pl.DataFrame] = {}
        for symbol in symbols:
            for product in products:
                df = self._query.klines(
                    exchange=venue, symbol=symbol, start=start, end=end
                )
                if df.height == 0:
                    continue
                frames[(venue, symbol, product)] = df

        if not frames:
            raise BacktestDataError(
                f"no data for {venue} {symbols} {products} in [{start}, {end}]"
            )

        # union of all bar timestamps across symbol/product combos
        all_ts: set[int] = set()
        for df in frames.values():
            all_ts.update(int(t) for t in df["ts_ms"].to_list())

        for ts_ms in sorted(all_ts):
            bars: dict[tuple[str, str, Product], Bar] = {}
            for key, df in frames.items():
                row = df.filter(pl.col("ts_ms") == ts_ms)
                if row.height == 0:
                    continue
                bars[key] = Bar(
                    ts_ms=int(row["ts_ms"][0]),
                    venue=key[0],
                    symbol=key[1],
                    product=key[2],
                    open=float(row["open"][0]),
                    high=float(row["high"][0]),
                    low=float(row["low"][0]),
                    close=float(row["close"][0]),
                    volume=float(row["volume"][0]),
                )
            yield MarketSnapshot(ts_ms=ts_ms, bars=bars)

    def load_funding(
        self,
        *,
        venue: str,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame | None:
        try:
            df = self._query.funding_rates(
                exchange=venue, symbol=symbol, start=start, end=end
            )
        except Exception:
            return None
        if df.height == 0:
            return None
        return df
