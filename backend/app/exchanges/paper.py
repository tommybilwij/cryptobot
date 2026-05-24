"""In-memory paper exchange — deterministic fills for unit tests + dry-run.

Uses the same `execution.slippage_bps.{venue}` and `execution.fee_bps.{venue}.{product}`
registry keys as the Phase 4 backtest, so paper trading semantically matches backtest.
"""

from __future__ import annotations

import time
import uuid

from app.backtest.orders import Order
from app.backtest.state import Product
from app.exchanges.types import (
    Balance,
    ExchangePosition,
    OrderReceipt,
    OrderStatus,
)
from app.profile.params import ProfileParams

_BPS_DIVISOR = 10_000.0


class PaperExchange:
    """Deterministic in-memory exchange. ``set_mark_price`` controls fill price."""

    def __init__(
        self,
        *,
        venue: str,
        params: ProfileParams,
        initial_cash: float,
    ) -> None:
        self.name = venue
        self._venue = venue
        self._params = params
        self._cash: float = initial_cash
        self._positions: dict[tuple[str, Product], ExchangePosition] = {}
        self._marks: dict[tuple[str, Product], float] = {}
        self._orders: dict[str, OrderStatus] = {}

    def set_mark_price(self, symbol: str, product: Product, px: float) -> None:
        """Test helper: set the mark price used for fills + mark-to-market."""
        self._marks[(symbol, product)] = px

    async def fetch_balance(self, quote_currency: str) -> Balance:
        return Balance(
            venue=self._venue,
            quote_currency=quote_currency,
            free=self._cash,
            locked=0.0,
        )

    async def fetch_positions(self) -> tuple[ExchangePosition, ...]:
        return tuple(self._positions.values())

    async def fetch_mark_price(self, symbol: str, product: Product) -> float:
        mark = self._marks.get((symbol, product))
        if mark is None:
            raise KeyError(f"no mark set for {symbol}/{product}")
        return mark

    async def place_order(self, order: Order) -> OrderReceipt:
        order_id = uuid.uuid4().hex
        submitted_ts_ms = int(time.time() * 1000)
        status = self._simulate_fill(order, order_id)
        self._orders[order_id] = status
        return OrderReceipt(
            order_id=order_id,
            venue=self._venue,
            symbol=order.symbol,
            submitted_ts_ms=submitted_ts_ms,
        )

    async def fetch_order(self, order_id: str) -> OrderStatus:
        if order_id not in self._orders:
            raise KeyError(f"unknown order {order_id}")
        return self._orders[order_id]

    async def cancel_order(self, order_id: str) -> None:
        # Market orders fill immediately; cancel is a no-op
        return

    def _simulate_fill(self, order: Order, order_id: str) -> OrderStatus:
        mark = self._marks.get((order.symbol, order.product))
        if mark is None:
            return OrderStatus(
                order_id=order_id, status="rejected", fill_px=None,
                filled_qty_base=0.0, fee_quote=0.0,
                raw={"reason": f"no mark for {order.symbol}/{order.product}"},
            )
        slip_bps = float(self._params.get(f"execution.slippage_bps.{self._venue}"))
        fee_bps = float(
            self._params.get(f"execution.fee_bps.{self._venue}.{order.product}")
        )
        slip = slip_bps / _BPS_DIVISOR
        if order.order_type == "market":
            fill_px = mark * (1.0 + slip) if order.side == "buy" else mark * (1.0 - slip)
        else:
            # Limit orders: assume fill iff mark touched the limit
            if order.limit_px is None:
                return OrderStatus(
                    order_id=order_id, status="rejected", fill_px=None,
                    filled_qty_base=0.0, fee_quote=0.0,
                    raw={"reason": "limit order without limit_px"},
                )
            if order.side == "buy" and mark <= order.limit_px:
                fill_px = order.limit_px
            elif order.side == "sell" and mark >= order.limit_px:
                fill_px = order.limit_px
            else:
                return OrderStatus(
                    order_id=order_id, status="pending", fill_px=None,
                    filled_qty_base=0.0, fee_quote=0.0, raw={},
                )
        notional = abs(order.qty_base) * fill_px
        fee = notional * (fee_bps / _BPS_DIVISOR)
        if order.side == "buy":
            cost = notional + fee
            if cost > self._cash:
                return OrderStatus(
                    order_id=order_id, status="rejected", fill_px=None,
                    filled_qty_base=0.0, fee_quote=0.0,
                    raw={"reason": f"insufficient cash {self._cash} < {cost}"},
                )
            self._cash -= cost
        else:
            self._cash += notional - fee

        self._apply_position(order, fill_px)
        return OrderStatus(
            order_id=order_id, status="filled", fill_px=fill_px,
            filled_qty_base=order.qty_base, fee_quote=fee, raw={},
        )

    def _apply_position(self, order: Order, fill_px: float) -> None:
        key = (order.symbol, order.product)
        delta = order.qty_base if order.side == "buy" else -order.qty_base
        existing = self._positions.get(key)
        if existing is None:
            self._positions[key] = ExchangePosition(
                venue=self._venue, symbol=order.symbol, product=order.product,
                qty_base=delta, avg_entry_px=fill_px,
                mark_px=fill_px, unrealized_pnl_quote=0.0,
            )
            return
        new_qty = existing.qty_base + delta
        if new_qty == 0.0:
            del self._positions[key]
            return
        same_sign = (delta * existing.qty_base) > 0
        if same_sign:
            new_avg = (
                (existing.avg_entry_px * abs(existing.qty_base))
                + (fill_px * abs(delta))
            ) / (abs(existing.qty_base) + abs(delta))
        else:
            new_avg = existing.avg_entry_px
        self._positions[key] = ExchangePosition(
            venue=self._venue, symbol=order.symbol, product=order.product,
            qty_base=new_qty, avg_entry_px=new_avg,
            mark_px=fill_px, unrealized_pnl_quote=0.0,
        )
