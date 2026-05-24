"""Equity curve → summary metrics (total_return, sharpe, max_drawdown, num_trades).

Sharpe is annualised with minutes-per-year × seconds-per-minute / bar_interval_s.
Risk-free rate = 0 (matches HLP-vault benchmark convention).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import polars as pl

from app.profile.params import ProfileParams

_SECONDS_PER_MINUTE = 60.0
_MIN_RETURNS_FOR_SHARPE = 2


@dataclass(frozen=True)
class BacktestMetrics:
    total_return: float
    sharpe: float
    max_drawdown: float
    num_trades: int


def compute_metrics(
    equity_curve: pl.DataFrame,
    *,
    params: ProfileParams,
    num_trades: int = 0,
) -> BacktestMetrics:
    if equity_curve.height < _MIN_RETURNS_FOR_SHARPE:
        return BacktestMetrics(
            total_return=0.0, sharpe=0.0, max_drawdown=0.0, num_trades=num_trades
        )

    equity = equity_curve["equity"].to_list()
    first = equity[0]
    last = equity[-1]
    total_return = (last - first) / first if first != 0.0 else 0.0

    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0.0:
            dd = (value - peak) / peak
            max_dd = min(max_dd, dd)

    returns: list[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        if prev != 0.0:
            returns.append((equity[i] - prev) / prev)

    minutes_per_year = float(params.get("metrics.minutes_per_year"))
    bar_interval_s = float(params.get("backtest.bar_interval_s"))
    bars_per_year = minutes_per_year * (_SECONDS_PER_MINUTE / bar_interval_s)

    if len(returns) < _MIN_RETURNS_FOR_SHARPE:
        sharpe = 0.0
    else:
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(var)
        sharpe = (mean / std) * math.sqrt(bars_per_year) if std > 0.0 else 0.0

    return BacktestMetrics(
        total_return=total_return,
        sharpe=sharpe,
        max_drawdown=max_dd,
        num_trades=num_trades,
    )
