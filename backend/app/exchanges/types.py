"""Frozen dataclasses returned by Exchange adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.backtest.state import Product


@dataclass(frozen=True)
class Balance:
    venue: str
    quote_currency: str
    free: float
    locked: float


@dataclass(frozen=True)
class ExchangePosition:
    venue: str
    symbol: str
    product: Product
    qty_base: float
    avg_entry_px: float
    mark_px: float
    unrealized_pnl_quote: float


@dataclass(frozen=True)
class OrderReceipt:
    order_id: str
    venue: str
    symbol: str
    submitted_ts_ms: int


_OrderStatusLiteral = Literal[
    "pending", "filled", "partially_filled", "cancelled", "rejected"
]


@dataclass(frozen=True)
class OrderStatus:
    order_id: str
    status: _OrderStatusLiteral
    fill_px: float | None
    filled_qty_base: float
    fee_quote: float
    raw: dict[str, Any]
