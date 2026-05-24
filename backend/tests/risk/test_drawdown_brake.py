"""Tests for ``DrawdownBrake`` — peak ratcheting + trigger halt."""

from __future__ import annotations

import pytest

from app.profile.params import ProfileParams
from app.risk.drawdown_brake import DrawdownBrake
from app.risk.exceptions import DrawdownBrakeHalt


def _brake(peak: float = 0.0, trigger_pct: float = 0.05) -> DrawdownBrake:
    """Build a brake from a synthetic profile (no DB)."""
    return DrawdownBrake(
        params=ProfileParams(
            profile={
                "risk": {
                    "drawdown_brake": {
                        "peak_equity": peak,
                        "trigger_pct": trigger_pct,
                    }
                }
            }
        )
    )


def test_seeds_peak_on_first_tick() -> None:
    """Cold start (peak=0): the first positive equity becomes the peak."""
    brake = _brake(peak=0.0)
    assert brake.peak == 0.0
    brake.check(10_000.0)
    assert brake.peak == 10_000.0


def test_updates_peak_on_new_high() -> None:
    """A new high ratchets the peak upward."""
    brake = _brake(peak=10_000.0)
    brake.check(11_000.0)
    assert brake.peak == 11_000.0


def test_halts_at_trigger_threshold() -> None:
    """Equity at 5.01% drop below peak (trigger=5%) raises DrawdownBrakeHalt."""
    brake = _brake(peak=10_000.0, trigger_pct=0.05)
    with pytest.raises(DrawdownBrakeHalt):
        brake.check(9_499.0)


def test_holds_above_trigger() -> None:
    """Equity at 3% drop (under 5% trigger) does NOT raise."""
    brake = _brake(peak=10_000.0, trigger_pct=0.05)
    brake.check(9_700.0)
    assert brake.peak == 10_000.0  # peak unchanged (not a new high)


def test_zero_peak_no_halt() -> None:
    """Cold start with peak=0: any equity, even a drop, never halts."""
    brake = _brake(peak=0.0, trigger_pct=0.05)
    brake.check(-100.0)  # would be a giant drawdown if peak were positive
    assert brake.peak == 0.0  # no positive equity yet — still cold
