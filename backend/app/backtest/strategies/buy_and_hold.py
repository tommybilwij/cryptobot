"""BuyAndHoldStrategy — opens a single long position on first tick, holds forever.

Engine validator: exercises basic P&L accumulation. Sized via the registry
(``backtest.initial_cash_quote_usdc`` → buy ~that much notional at the first
available close).
"""

from __future__ import annotations

from app.backtest.orders import Order
from app.backtest.state import MarketState
from app.profile.params import ProfileParams


class BuyAndHoldStrategy:
    name = "buy_and_hold"

    def __init__(self, *, venue: str, symbol: str) -> None:
        self._venue = venue
        self._symbol = symbol

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        # If we already hold any position in this (venue, symbol, spot), do nothing.
        for pos in state.positions:
            if (pos.venue, pos.symbol, pos.product) == (self._venue, self._symbol, "spot"):
                return []
        # Initial buy sized by initial_cash_quote_usdc / current close.
        bar = state.snapshot.bars.get((self._venue, self._symbol, "spot"))
        if bar is None:
            return []
        notional = float(params.get("backtest.initial_cash_quote_usdc"))
        qty = notional / bar.close
        return [
            Order(
                venue=self._venue,
                symbol=self._symbol,
                product="spot",
                side="buy",
                qty_base=qty,
                order_type="market",
            )
        ]
