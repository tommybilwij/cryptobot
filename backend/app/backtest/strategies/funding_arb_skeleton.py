"""FundingArbSkeleton — minimal delta-neutral validator (long spot + short perp).

Engine validator only. Real Strategy A (entry/exit logic, calibration,
capacity caps) lands in Phase 6.

Sizes the hedge pair using a fraction of ``backtest.initial_cash_quote_usdc``
(spot leg notional, registry-driven). Hold-forever — opens once, never
rebalances.
"""

from __future__ import annotations

from app.backtest.orders import Order
from app.backtest.state import MarketState
from app.profile.params import ProfileParams


class FundingArbSkeleton:
    name = "funding_arb_skeleton"

    def __init__(self, *, venue: str, symbol: str) -> None:
        self._venue = venue
        self._symbol = symbol

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        has_spot = any(
            (p.venue, p.symbol, p.product) == (self._venue, self._symbol, "spot")
            for p in state.positions
        )
        has_perp = any(
            (p.venue, p.symbol, p.product) == (self._venue, self._symbol, "perp")
            for p in state.positions
        )
        if has_spot and has_perp:
            return []
        spot_bar = state.snapshot.bars.get((self._venue, self._symbol, "spot"))
        perp_bar = state.snapshot.bars.get((self._venue, self._symbol, "perp"))
        if spot_bar is None or perp_bar is None:
            return []
        initial_cash = float(params.get("backtest.initial_cash_quote_usdc"))
        fraction = float(params.get("backtest.funding_arb_skeleton.hedge_size_fraction"))
        spot_notional = initial_cash * fraction
        qty = spot_notional / spot_bar.close
        return [
            Order(
                venue=self._venue, symbol=self._symbol, product="spot",
                side="buy", qty_base=qty, order_type="market",
            ),
            Order(
                venue=self._venue, symbol=self._symbol, product="perp",
                side="sell", qty_base=qty, order_type="market",
            ),
        ]
