"""MarketDataSource Protocol — common interface for exchange downloaders.

Implementations live in sibling modules (``binance_vision.py``,
``bybit_public.py``, ``hyperliquid_archive.py``). Each one knows how to fetch
one calendar month of data for a given symbol + data type.

All methods return Polars DataFrames with the canonical schema (so downstream
``ParquetStore.write_*`` calls don't need per-source branching).

Canonical kline columns: ``ts_ms`` (int64, exchange time) + ``open / high /
low / close / volume`` (float64).

Canonical funding columns: ``ts_ms`` (int64) + ``predicted`` (float64) +
``realized`` (float64 or null until the funding period closes).
"""

from __future__ import annotations

from typing import Protocol

import polars as pl


class MarketDataSource(Protocol):
    """One implementation per exchange. Each fetches one calendar month."""

    name: str

    async def fetch_klines_1m(self, symbol: str, year: int, month: int) -> pl.DataFrame:
        """Return a Polars frame with columns ts_ms / open / high / low / close / volume."""
        ...

    async def fetch_funding_rates(
        self, symbol: str, year: int, month: int
    ) -> pl.DataFrame:
        """Return a Polars frame with columns ts_ms / predicted / realized.

        Raises NotImplementedError on venues that don't expose funding rates
        (e.g. Binance spot — caller should not invoke for spot pairs).
        """
        ...

    async def fetch_open_interest(
        self, symbol: str, year: int, month: int
    ) -> pl.DataFrame:
        """Return a Polars frame with columns ts_ms / oi_base / oi_quote.

        Raises NotImplementedError where unsupported.
        """
        ...
