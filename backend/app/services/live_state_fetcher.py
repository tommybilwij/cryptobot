"""LiveStateFetcher — live MarketState builder from an Exchange adapter."""

from __future__ import annotations

import time

from app.backtest.state import Bar, MarketSnapshot, MarketState, Position, Product
from app.exchanges.base import Exchange

_PRODUCTS: tuple[Product, ...] = ("spot", "perp")

_MS_PER_SECOND = 1000


class LiveStateFetcher:
    """Build a ``MarketState`` for the live engine from an ``Exchange`` adapter.

    The live engine treats the returned state identically to the backtester's
    per-tick state, so the same ``Strategy.evaluate(state, params)`` runs
    against both. Mark prices are reused for all four OHLC fields and volume
    is zeroed — strategies that need real bars must consume them from the
    market_data feed, not this fetcher.
    """

    def __init__(self, *, exchanges: dict[str, Exchange], venue: str) -> None:
        self._exchanges = exchanges
        self._venue = venue

    async def fetch_market_state(
        self, *, symbols: list[str], quote_currency: str = "USDC"
    ) -> MarketState:
        """Fetch balance + positions + mark prices + funding for ``symbols``.

        Symbols without a mark on either product are silently skipped (e.g.
        spot-only listings). Funding rates that the adapter returns ``None``
        for are omitted from the snapshot rather than recorded as 0.
        """
        exchange = self._exchanges[self._venue]
        ts_ms = int(time.time() * _MS_PER_SECOND)
        balance = await exchange.fetch_balance(quote_currency)
        ex_positions = await exchange.fetch_positions()
        positions = tuple(
            Position(
                venue=p.venue,
                symbol=p.symbol,
                product=p.product,
                qty_base=p.qty_base,
                avg_entry_px=p.avg_entry_px,
            )
            for p in ex_positions
        )
        bars: dict[tuple[str, str, Product], Bar] = {}
        funding_rates: dict[tuple[str, str], float] = {}
        for symbol in symbols:
            for product in _PRODUCTS:
                try:
                    mark = await exchange.fetch_mark_price(symbol, product)
                except (KeyError, RuntimeError):
                    continue
                bars[(self._venue, symbol, product)] = Bar(
                    ts_ms=ts_ms,
                    venue=self._venue,
                    symbol=symbol,
                    product=product,
                    open=mark,
                    high=mark,
                    low=mark,
                    close=mark,
                    volume=0.0,
                )
            funding = await exchange.fetch_funding_rate(symbol)
            if funding is not None:
                funding_rates[(self._venue, symbol)] = funding
        snapshot = MarketSnapshot(
            ts_ms=ts_ms, bars=bars, funding_rates=funding_rates
        )
        return MarketState(
            snapshot=snapshot,
            positions=positions,
            cash_quote=balance.free,
        )
