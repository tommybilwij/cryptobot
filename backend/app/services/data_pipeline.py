"""DataPipelineService — orchestrates download + write across data sources."""

from __future__ import annotations

from app.market_data.base import MarketDataSource
from app.market_data.parquet_store import ParquetStore


class UnknownSource(KeyError):
    """Raised when the pipeline is asked to refresh from an unregistered source."""


class DataPipelineService:
    def __init__(
        self,
        *,
        store: ParquetStore,
        sources: dict[str, MarketDataSource],
    ) -> None:
        self._store = store
        self._sources = sources

    async def refresh_klines_1m(
        self, exchange: str, symbol: str, *, year: int, month: int
    ) -> None:
        source = self._sources.get(exchange)
        if source is None:
            raise UnknownSource(exchange)
        df = await source.fetch_klines_1m(symbol, year, month)
        self._store.write_klines(exchange, symbol, df, year=year, month=month)

    async def refresh_funding_rates(
        self, exchange: str, symbol: str, *, year: int, month: int
    ) -> None:
        source = self._sources.get(exchange)
        if source is None:
            raise UnknownSource(exchange)
        df = await source.fetch_funding_rates(symbol, year, month)
        self._store.write_funding(exchange, symbol, df, year=year, month=month)

    async def refresh_open_interest(
        self, exchange: str, symbol: str, *, year: int, month: int
    ) -> None:
        source = self._sources.get(exchange)
        if source is None:
            raise UnknownSource(exchange)
        df = await source.fetch_open_interest(symbol, year, month)
        self._store.write_open_interest(exchange, symbol, df, year=year, month=month)
