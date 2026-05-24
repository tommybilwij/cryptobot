"""Exchange Protocol — common interface for live + paper adapters."""

from __future__ import annotations

from typing import Protocol

from app.backtest.orders import Order
from app.backtest.state import Product
from app.exchanges.types import (
    Balance,
    ExchangePosition,
    OrderReceipt,
    OrderStatus,
)


class Exchange(Protocol):
    """One implementation per venue (or PaperExchange for tests + dry-run)."""

    name: str

    async def fetch_balance(self, quote_currency: str) -> Balance:
        """Return free + locked balance of ``quote_currency`` at the venue."""
        ...

    async def fetch_positions(self) -> tuple[ExchangePosition, ...]:
        """Return all open positions across spot + perp on this venue."""
        ...

    async def place_order(self, order: Order) -> OrderReceipt:
        """Submit ``order``. Returns receipt with the venue-assigned ``order_id``."""
        ...

    async def fetch_order(self, order_id: str) -> OrderStatus:
        """Get current status of an order placed via ``place_order``."""
        ...

    async def cancel_order(self, order_id: str) -> None:
        """Best-effort cancel. No-op if already filled/cancelled."""
        ...

    async def fetch_mark_price(self, symbol: str, product: Product) -> float:
        """Current mark / index / last-price for the (symbol, product) pair."""
        ...
