"""Strategy A — funding-rate arbitrage.

Delta-neutral long-spot + short-perp when 8h funding is above the entry
threshold; close the hedge when funding decays below the exit threshold.

All thresholds + sizing live in the profile registry (Constraint #1).
"""

from __future__ import annotations

from app.backtest.orders import Order
from app.backtest.state import MarketState
from app.profile.params import ProfileParams

_BPS_DIVISOR = 10_000.0


class FundingArbStrategy:
    name = "funding_arb"

    def __init__(self, *, venue: str, symbol: str) -> None:
        self._venue = venue
        self._symbol = symbol

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        funding = state.snapshot.funding_rates.get((self._venue, self._symbol))
        if funding is None:
            return []
        # Convert to "per 8h bps" — funding rate is the per-interval rate already.
        # Phase 6 assumes funding_rates are 8h-equivalent; mixed-cadence handling
        # is a Phase 7+ concern when we wire venue-specific cadences.
        funding_bps_per_8h = funding * _BPS_DIVISOR
        entry = float(params.get("strategies.funding_arb.entry_bps_per_8h"))
        if funding_bps_per_8h < entry:
            return []
        # Other branches (hedged + open hedge + sizing) ship in subsequent tasks.
        return []
