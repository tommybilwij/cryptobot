"""Order + Fill dataclasses — strategies return ``list[Order]``; engine produces ``Fill``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.backtest.state import Product

OrderType = Literal["market", "limit"]
Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Order:
    venue: str
    symbol: str
    product: Product
    side: Side
    qty_base: float
    order_type: OrderType
    limit_px: float | None = None


@dataclass(frozen=True)
class Fill:
    ts_ms: int
    order: Order
    fill_px: float
    fee_quote: float

    @property
    def qty_base_signed(self) -> float:
        return self.order.qty_base if self.order.side == "buy" else -self.order.qty_base
