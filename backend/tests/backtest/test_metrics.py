"""Tests for backtest metrics — Sharpe (24/7 annualised), max_dd, total_return."""

from __future__ import annotations

import math

import polars as pl

from app.backtest.metrics import compute_metrics
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def test_total_return_simple() -> None:
    curve = pl.DataFrame({"ts_ms": [0, 60_000], "equity": [10_000.0, 11_000.0]})
    metrics = compute_metrics(curve, params=_params())
    assert metrics.total_return == 0.1


def test_max_drawdown_simple() -> None:
    # 10000 → 12000 (peak) → 9000 (trough) → 11000
    # dd = (9000 - 12000) / 12000 = -0.25
    curve = pl.DataFrame(
        {"ts_ms": [0, 60_000, 120_000, 180_000], "equity": [10_000.0, 12_000.0, 9_000.0, 11_000.0]}
    )
    metrics = compute_metrics(curve, params=_params())
    assert metrics.max_drawdown == -0.25


def test_sharpe_returns_finite_on_alternating_returns() -> None:
    n = 1000
    equities = [10_000.0]
    for i in range(1, n):
        rate = 0.0001 if i % 2 == 0 else -0.00005
        equities.append(equities[-1] * (1 + rate))
    curve = pl.DataFrame({"ts_ms": list(range(0, n * 60_000, 60_000)), "equity": equities})
    metrics = compute_metrics(curve, params=_params())
    assert math.isfinite(metrics.sharpe)


def test_num_trades_counted_from_trade_log() -> None:
    curve = pl.DataFrame({"ts_ms": [0, 60_000], "equity": [10_000.0, 10_010.0]})
    metrics = compute_metrics(curve, params=_params(), num_trades=3)
    assert metrics.num_trades == 3


def test_empty_curve_returns_zeros() -> None:
    curve = pl.DataFrame({"ts_ms": [], "equity": []}, schema={"ts_ms": pl.Int64, "equity": pl.Float64})
    metrics = compute_metrics(curve, params=_params())
    assert metrics.total_return == 0.0
    assert metrics.sharpe == 0.0
    assert metrics.max_drawdown == 0.0
