"""Strategy A — funding-rate arbitrage.

Delta-neutral long-spot + short-perp when 8h funding is above the entry
threshold; close the hedge when funding decays below the exit threshold.

All thresholds + sizing live in the profile registry (Constraint #1).
"""

from __future__ import annotations

from typing import Literal

from app.backtest.orders import Order
from app.backtest.state import MarketState, Position
from app.profile.params import ProfileParams
from app.risk.sizing import SizingService

_BPS_DIVISOR = 10_000.0
# Phase 10 placeholder vol; Phase 11+ wires a real rolling stdev estimator.
_PHASE_10_VOL_PLACEHOLDER = 0.6


class FundingArbStrategy:
    name = "funding_arb"

    def __init__(self, *, venue: str, symbol: str) -> None:
        self._venue = venue
        self._symbol = symbol

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        funding = state.snapshot.funding_rates.get((self._venue, self._symbol))
        if funding is None:
            return []
        funding_bps_per_8h = funding * _BPS_DIVISOR
        spot_pos, perp_pos = self._find_position(state.positions)
        return self._decide(funding_bps_per_8h, spot_pos, perp_pos, state, params)

    def _decide(
        self,
        funding_bps_per_8h: float,
        spot_pos: Position | None,
        perp_pos: Position | None,
        state: MarketState,
        params: ProfileParams,
    ) -> list[Order]:
        # Flat → maybe enter
        if spot_pos is None and perp_pos is None:
            entry = float(params.get("strategies.funding_arb.entry_bps_per_8h"))
            if funding_bps_per_8h < entry:
                return []
            return self._open_hedge(state, params)

        # Hedged → maybe exit
        if spot_pos is not None and perp_pos is not None:
            exit_threshold = float(
                params.get("strategies.funding_arb.exit_bps_per_8h")
            )
            if funding_bps_per_8h > exit_threshold:
                return []
            return self._close_hedge(spot_pos, perp_pos)

        # Orphan spot → close spot
        if spot_pos is not None:
            return [
                Order(
                    venue=self._venue,
                    symbol=self._symbol,
                    product="spot",
                    side="sell",
                    qty_base=abs(spot_pos.qty_base),
                    order_type="market",
                )
            ]

        # Orphan perp → close perp
        assert perp_pos is not None
        side: Literal["buy", "sell"] = (
            "buy" if perp_pos.qty_base < 0.0 else "sell"
        )
        return [
            Order(
                venue=self._venue,
                symbol=self._symbol,
                product="perp",
                side=side,
                qty_base=abs(perp_pos.qty_base),
                order_type="market",
            )
        ]

    def _find_position(
        self, positions: tuple[Position, ...]
    ) -> tuple[Position | None, Position | None]:
        spot: Position | None = None
        perp: Position | None = None
        for p in positions:
            if (p.venue, p.symbol) != (self._venue, self._symbol):
                continue
            if p.product == "spot":
                spot = p
            elif p.product == "perp":
                perp = p
        return spot, perp

    def _open_hedge(
        self, state: MarketState, params: ProfileParams
    ) -> list[Order]:
        spot_bar = state.snapshot.bars.get((self._venue, self._symbol, "spot"))
        perp_bar = state.snapshot.bars.get((self._venue, self._symbol, "perp"))
        if spot_bar is None or perp_bar is None:
            return []
        if spot_bar.close <= 0.0:
            return []
        max_notional = float(params.get("strategies.funding_arb.max_notional_usdc"))
        cash_frac = float(params.get("strategies.funding_arb.max_cash_fraction"))
        kelly_enabled = float(params.get("risk.kelly.enabled")) > 0.0
        if kelly_enabled:
            # Kelly + vol target + drawdown ramp. Phase 10: vol is a stub; the
            # real estimator lands in Phase 11. Equity-without-MTM (cash_quote)
            # is a deliberate simplification for the opt-in path — the live
            # runner has the MTM, but the engine doesn't yet expose it here.
            sizer = SizingService(params=params)
            funding_rate = state.snapshot.funding_rates.get(
                (self._venue, self._symbol), 0.0
            )
            peak_equity = float(params.get("risk.drawdown_brake.peak_equity"))
            target = sizer.compute_notional(
                funding_rate_per_interval=funding_rate,
                realized_vol=_PHASE_10_VOL_PLACEHOLDER,
                cash_quote=state.cash_quote,
                peak_equity=peak_equity,
                current_equity=state.cash_quote,
                max_notional_cap=max_notional,
            )
        else:
            target = min(max_notional, state.cash_quote * cash_frac)
        if target <= 0.0:
            return []
        qty = target / spot_bar.close
        return [
            Order(
                venue=self._venue,
                symbol=self._symbol,
                product="spot",
                side="buy",
                qty_base=qty,
                order_type="market",
            ),
            Order(
                venue=self._venue,
                symbol=self._symbol,
                product="perp",
                side="sell",
                qty_base=qty,
                order_type="market",
            ),
        ]

    def _close_hedge(
        self, spot_pos: Position, perp_pos: Position
    ) -> list[Order]:
        return [
            Order(
                venue=self._venue,
                symbol=self._symbol,
                product="spot",
                side="sell",
                qty_base=abs(spot_pos.qty_base),
                order_type="market",
            ),
            Order(
                venue=self._venue,
                symbol=self._symbol,
                product="perp",
                side="buy",
                qty_base=abs(perp_pos.qty_base),
                order_type="market",
            ),
        ]
