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
                df = self._query.klines(exchange=venue, symbol=symbol, start=start, end=end)
                if df.height == 0:
                    continue
                frames[(venue, symbol, product)] = df

        if not frames:
            raise BacktestDataError(f"no data for {venue} {symbols} {products} in [{start}, {end}]")

        # Preload funding rates per (venue, symbol), indexed by ts_ms.
        # We index by ts_ms so per-tick lookup is O(1) — funding events are
        # sparse (~1 every 8h on Binance perp) but bars are dense (1/min), so
        # this dict is small and the snapshot inner loop stays cheap.
        funding_index = self._build_funding_index(
            venue=venue, symbols=symbols, start=start, end=end
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

            # Surface funding rates for any (venue, symbol) that has a
            # funding event at this exact ts_ms. Most ticks will produce
            # an empty dict, matching the MarketSnapshot default.
            funding_rates: dict[tuple[str, str], float] = {}
            for vs_key, ts_to_rate in funding_index.items():
                rate = ts_to_rate.get(ts_ms)
                if rate is not None:
                    funding_rates[vs_key] = rate

            yield MarketSnapshot(ts_ms=ts_ms, bars=bars, funding_rates=funding_rates)

    def load_funding(
        self,
        *,
        venue: str,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame | None:
        try:
            df = self._query.funding_rates(exchange=venue, symbol=symbol, start=start, end=end)
        except Exception:
            return None
        if df.height == 0:
            return None
        return df

    def _build_funding_index(
        self,
        *,
        venue: str,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> dict[tuple[str, str], dict[int, float]]:
        """Preload funding rates per (venue, symbol), indexed by ts_ms.

        Extracted from `iter_snapshots` so the snapshot loop stays under
        the branch-complexity limit. Returns an empty dict when no funding
        data exists for any requested symbol.
        """
        funding_index: dict[tuple[str, str], dict[int, float]] = {}
        for symbol in symbols:
            fdf = self.load_funding(venue=venue, symbol=symbol, start=start, end=end)
            if fdf is None:
                continue
            ts_to_rate: dict[int, float] = {}
            for funding_row in fdf.iter_rows(named=True):
                ts_to_rate[int(funding_row["ts_ms"])] = float(funding_row["realized"])
            funding_index[(venue, symbol)] = ts_to_rate
        return funding_index
