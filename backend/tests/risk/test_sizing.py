"""Tests for ``SizingService`` — Kelly + vol target + drawdown ramp."""

from __future__ import annotations

from app.profile.params import ProfileParams
from app.risk.sizing import SizingService


def _sizer() -> SizingService:
    """Build a sizer against the empty profile (everything comes from registry defaults)."""
    return SizingService(params=ProfileParams(profile={}))


def test_kelly_zero_funding_no_position() -> None:
    """Funding=0 → Kelly=0 → no notional, regardless of cash / cap."""
    notional = _sizer().compute_notional(
        funding_rate_per_interval=0.0,
        realized_vol=0.6,
        cash_quote=10_000.0,
        peak_equity=10_000.0,
        current_equity=10_000.0,
        max_notional_cap=5_000.0,
    )
    assert notional == 0.0


def test_kelly_clipped_at_baseline_cap() -> None:
    """Huge funding + low vol → Kelly explodes; baseline_cap (2%) clamps it."""
    notional = _sizer().compute_notional(
        funding_rate_per_interval=0.01,  # 100 bps per 8h (extreme)
        realized_vol=0.05,  # 5% annualised — very low
        cash_quote=10_000.0,
        peak_equity=10_000.0,
        current_equity=10_000.0,
        max_notional_cap=100_000.0,
    )
    # baseline_cap default 0.02 → max notional = cash * 0.02 = 200 (Kelly side).
    # Note the min(kelly, vol_target_frac) also bounds at vol_target/vol;
    # both branches are <= cap, so notional <= 200.
    assert notional <= 200.0 + 1.0


def test_zero_vol_returns_zero() -> None:
    """Degenerate vol → divide-by-zero guard → no notional."""
    notional = _sizer().compute_notional(
        funding_rate_per_interval=0.001,
        realized_vol=0.0,
        cash_quote=10_000.0,
        peak_equity=10_000.0,
        current_equity=10_000.0,
        max_notional_cap=5_000.0,
    )
    assert notional == 0.0


def test_drawdown_brake_reduces_size_at_trigger() -> None:
    """Equity 10% below peak (between 5% trigger and 15% full) → smaller notional."""
    no_dd = _sizer().compute_notional(
        funding_rate_per_interval=0.001,
        realized_vol=0.6,
        cash_quote=10_000.0,
        peak_equity=10_000.0,
        current_equity=10_000.0,
        max_notional_cap=5_000.0,
    )
    with_dd = _sizer().compute_notional(
        funding_rate_per_interval=0.001,
        realized_vol=0.6,
        cash_quote=10_000.0,
        peak_equity=10_000.0,
        current_equity=9_000.0,  # 10% drawdown
        max_notional_cap=5_000.0,
    )
    assert with_dd < no_dd
    assert with_dd > 0.0


def test_drawdown_brake_at_full_uses_min_mult() -> None:
    """Equity ≥ full_pct (15%) below peak → multiplier collapses to min_mult (0.25)."""
    no_dd = _sizer().compute_notional(
        funding_rate_per_interval=0.001,
        realized_vol=0.6,
        cash_quote=10_000.0,
        peak_equity=10_000.0,
        current_equity=10_000.0,
        max_notional_cap=5_000.0,
    )
    at_full = _sizer().compute_notional(
        funding_rate_per_interval=0.001,
        realized_vol=0.6,
        cash_quote=10_000.0,
        peak_equity=10_000.0,
        current_equity=8_000.0,  # 20% drawdown > full_pct 15%
        max_notional_cap=5_000.0,
    )
    # min_mult default 0.25 → expect ~25% of full.
    assert 0.1 * no_dd <= at_full <= 0.4 * no_dd


def test_caps_at_max_notional() -> None:
    """Whatever fraction wins, the strategy-level max_notional_cap is final."""
    notional = _sizer().compute_notional(
        funding_rate_per_interval=0.001,
        realized_vol=0.6,
        cash_quote=1_000_000.0,
        peak_equity=1_000_000.0,
        current_equity=1_000_000.0,
        max_notional_cap=5_000.0,
    )
    assert notional <= 5_000.0
