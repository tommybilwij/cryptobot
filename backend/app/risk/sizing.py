"""SizingService — Kelly fraction + vol targeting + drawdown brake multiplier.

Replaces Phase 6's inline ``min(max_notional, cash * fraction)`` with a
unified sizing service. Every threshold is sourced from the profile
registry (Constraint #1); this module reads no literals beyond
unit-of-measure constants.

Formula:
    kelly_frac      = (funding_rate_per_interval * intervals_per_year)
                      / (realized_vol ** 2)
                      * risk.kelly.fraction
                      (clamped to [0, risk.kelly.baseline_cap])
    vol_target_frac = risk.vol_target.target_pct / realized_vol
                      (clamped to [0, risk.kelly.baseline_cap])
    drawdown_mult   = 1.0                        if dd < trigger_pct
                      linear ramp to min_mult    while trigger_pct <= dd < full_pct
                      min_mult                    if dd >= full_pct
    target_notional = cash_quote
                      * min(kelly_frac, vol_target_frac, max_cash_fraction)
                      * drawdown_mult
                      (capped at max_notional_cap)
"""

from __future__ import annotations

from app.profile.params import ProfileParams

_MIN_VOL = 1e-6
_TWO = 2


class SizingService:
    """Pure sizing function. Reads every knob from the registry on each call.

    Per Constraint #2 the same service runs in backtest and live: the only
    inputs are the live state (funding rate, vol, cash, equity) and the
    profile-resolved params. Two callers with the same ``profile_id`` will
    compute identical notionals.
    """

    def __init__(self, *, params: ProfileParams) -> None:
        self._params = params

    def compute_notional(
        self,
        *,
        funding_rate_per_interval: float,
        realized_vol: float,
        cash_quote: float,
        peak_equity: float,
        current_equity: float,
        max_notional_cap: float,
        intervals_per_year: float | None = None,
    ) -> float:
        """Return the target USDC notional for the spot leg.

        Args:
            funding_rate_per_interval: Funding paid per interval as a decimal
                (e.g. 0.0008 = 8 bps per 8h on Binance).
            realized_vol: Annualised standard deviation of returns
                (e.g. 0.6 = 60% annualised vol).
            cash_quote: Free quote-currency balance available to deploy.
            peak_equity: Rolling peak equity (from ``DrawdownBrake``).
            current_equity: Live mark-to-market equity.
            max_notional_cap: Hard cap from the strategy registry — the
                returned value is min'd against this.
            intervals_per_year: Optional override for the annualisation
                factor. Strategy A passes the per-venue value
                (``exchanges.{venue}.funding_intervals_per_year``) so HL's
                hourly funding doesn't get sized under Binance's 8h cadence.
                When omitted, falls back to the legacy
                ``strategies.funding_arb.intervals_per_year`` for backward
                compatibility.

        Returns:
            Target notional in quote currency. Zero when funding is
            non-positive, vol is degenerate, or the drawdown brake at full
            halt collapses the multiplier all the way down to ``min_mult``.
        """
        if intervals_per_year is None:
            intervals_per_year = float(
                self._params.get("strategies.funding_arb.intervals_per_year")
            )
        baseline_cap = float(self._params.get("risk.kelly.baseline_cap"))
        kelly_fraction = float(self._params.get("risk.kelly.fraction"))
        vol_target = float(self._params.get("risk.vol_target.target_pct"))
        trigger_pct = float(self._params.get("risk.drawdown_brake.trigger_pct"))
        full_pct = float(self._params.get("risk.drawdown_brake.full_pct"))
        min_mult = float(self._params.get("risk.drawdown_brake.min_mult"))
        cash_frac_cap = float(self._params.get("strategies.funding_arb.max_cash_fraction"))

        # Kelly: annualised expected return / vol^2, scaled by fraction (half
        # Kelly by default). Degenerate vol short-circuits to zero.
        if realized_vol < _MIN_VOL:
            return 0.0
        annualised_return = funding_rate_per_interval * intervals_per_year
        kelly = (annualised_return / (realized_vol**_TWO)) * kelly_fraction
        if kelly <= 0.0:
            return 0.0
        kelly = min(kelly, baseline_cap)

        # Vol target: scale to target_pct / realized_vol, same Kelly cap.
        vol_target_frac = min(vol_target / realized_vol, baseline_cap)

        # Drawdown brake multiplier: linear ramp between trigger and full halt.
        mult = 1.0
        if peak_equity > 0.0 and current_equity < peak_equity:
            dd_pct = (peak_equity - current_equity) / peak_equity
            if dd_pct >= full_pct:
                mult = min_mult
            elif dd_pct >= trigger_pct:
                ramp = (dd_pct - trigger_pct) / (full_pct - trigger_pct)
                mult = 1.0 - ramp * (1.0 - min_mult)

        frac = min(kelly, vol_target_frac, cash_frac_cap)
        target = cash_quote * frac * mult
        return min(target, max_notional_cap)
