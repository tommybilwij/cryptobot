"""Drawdown brake — tracks rolling peak equity, halts on excessive drawdown.

Phase 8 ships binary halt at ``risk.drawdown_brake.trigger_pct`` (default 5%).
Graduated multipliers (Phase 10+) read ``risk.drawdown_brake.full_pct`` and
``min_mult`` to scale position sizes between trigger and full halt.

All thresholds and the initial peak are sourced from the profile registry —
no literals in this module (Constraint #1).
"""

from __future__ import annotations

from app.profile.params import ProfileParams
from app.risk.exceptions import DrawdownBrakeHalt


class DrawdownBrake:
    """Rolling peak-equity tracker that halts on a configured percentage drop.

    The brake seeds its peak from ``risk.drawdown_brake.peak_equity`` so a
    runner restart can resume tracking against the prior high-water mark.
    Each ``check(equity)`` call either ratchets the peak up or, once a peak
    has been established, raises ``DrawdownBrakeHalt`` if the current equity
    is below ``peak * (1 - trigger_pct)``.
    """

    def __init__(self, *, params: ProfileParams) -> None:
        self._params = params
        self._peak: float = float(params.get("risk.drawdown_brake.peak_equity"))

    @property
    def peak(self) -> float:
        """Current high-water mark."""
        return self._peak

    def check(self, equity: float) -> None:
        """Update peak if new high; raise ``DrawdownBrakeHalt`` if drop > trigger.

        Args:
            equity: Latest mark-to-market equity in quote currency.

        Raises:
            DrawdownBrakeHalt: When ``equity`` is below peak by more than the
                configured trigger percentage. Cold start (peak <= 0) never
                raises — the first positive equity becomes the seed peak.
        """
        if equity > self._peak:
            self._peak = equity
            return
        if self._peak <= 0.0:
            return  # cold start, no halt possible
        drawdown_pct = (equity - self._peak) / self._peak
        trigger = -abs(float(self._params.get("risk.drawdown_brake.trigger_pct")))
        if drawdown_pct < trigger:
            raise DrawdownBrakeHalt(
                f"equity {equity:.2f} below peak {self._peak:.2f} by "
                f"{drawdown_pct:.4f}, trigger={trigger:.4f}"
            )
