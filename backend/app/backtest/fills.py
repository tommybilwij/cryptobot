"""FillSimulator — applies constant-bps slippage + venue/product fees from profile."""

from __future__ import annotations

from app.backtest.orders import Fill, Order
from app.backtest.state import Bar, MarketSnapshot
from app.profile.params import ProfileParams

_BPS_DIVISOR = 10_000.0


class InsufficientCashError(RuntimeError):
    """Raised when a buy order would push cash below zero."""


class FillSimulator:
    def __init__(self, *, params: ProfileParams) -> None:
        self._params = params

    def fill(
        self,
        orders: list[Order],
        snapshot: MarketSnapshot,
        *,
        cash: float,
    ) -> tuple[list[Fill], float]:
        fills: list[Fill] = []
        cash_left = cash
        for order in orders:
            bar = snapshot.bars.get((order.venue, order.symbol, order.product))
            if bar is None:
                continue
            fill_px = self._compute_fill_px(order, bar)
            if fill_px is None:
                continue
            fee_bps = float(
                self._params.get(f"execution.fee_bps.{order.venue}.{order.product}")
            )
            notional = abs(order.qty_base) * fill_px
            fee = notional * (fee_bps / _BPS_DIVISOR)
            if order.side == "buy":
                cost = notional + fee
                if cost > cash_left:
                    raise InsufficientCashError(
                        f"buy {order.symbol} cost {cost:.2f} > cash {cash_left:.2f}"
                    )
                cash_left -= cost
            else:
                cash_left += notional - fee
            fills.append(
                Fill(ts_ms=snapshot.ts_ms, order=order, fill_px=fill_px, fee_quote=fee)
            )
        return fills, cash_left

    def _compute_fill_px(self, order: Order, bar: Bar) -> float | None:
        slippage_bps = float(
            self._params.get(f"execution.slippage_bps.{order.venue}")
        )
        slip = slippage_bps / _BPS_DIVISOR
        if order.order_type == "market":
            if order.side == "buy":
                return bar.close * (1.0 + slip)
            return bar.close * (1.0 - slip)
        # limit order
        if order.limit_px is None:
            return None
        if bar.low <= order.limit_px <= bar.high:
            return order.limit_px
        return None
