"""MetaAllocator — Sharpe-weighted allocation across strategies."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.profile.params import ProfileParams

_TWO = 2
_DEFAULT_SHARPE = 0.0
_EPSILON = 1e-9


@dataclass(frozen=True)
class StrategyAllocation:
    strategy_name: str
    weight: float
    sharpe_30d: float


class MetaAllocator:
    def __init__(self, *, params: ProfileParams) -> None:
        self._params = params

    def allocate(
        self,
        *,
        strategy_returns: dict[str, list[float]],
    ) -> tuple[StrategyAllocation, ...]:
        if not strategy_returns:
            return ()

        min_weight = float(self._params.get("strategies.meta_allocator.min_weight_pct"))
        max_weight = float(self._params.get("strategies.meta_allocator.max_weight_pct"))

        # Compute Sharpe per strategy
        sharpes: dict[str, float] = {}
        for name, returns in strategy_returns.items():
            sharpes[name] = self._sharpe(returns)

        # Positive-Sharpe normalisation; negatives floored at min_weight
        positives = {n: s for n, s in sharpes.items() if s > 0.0}
        if not positives:
            # All non-positive → equal weights
            n_strats = len(sharpes)
            equal_w = 1.0 / n_strats if n_strats > 0 else 0.0
            return tuple(
                StrategyAllocation(strategy_name=n, weight=equal_w, sharpe_30d=s)
                for n, s in sharpes.items()
            )

        positive_total = sum(positives.values())
        negative_count = len(sharpes) - len(positives)
        # Reserve min_weight for negatives
        reserved = min_weight * negative_count
        remaining = max(0.0, 1.0 - reserved)

        allocations: list[StrategyAllocation] = []
        for name, sharpe in sharpes.items():
            if sharpe > 0.0:
                raw_weight = (sharpe / positive_total) * remaining
                weight = min(max_weight, max(min_weight, raw_weight))
            else:
                weight = min_weight
            allocations.append(
                StrategyAllocation(strategy_name=name, weight=weight, sharpe_30d=sharpe)
            )

        # Renormalise to exactly 1.0 (clipping may push sum off)
        total_w = sum(a.weight for a in allocations)
        if total_w < _EPSILON:
            return tuple(allocations)
        return tuple(
            StrategyAllocation(
                strategy_name=a.strategy_name,
                weight=a.weight / total_w,
                sharpe_30d=a.sharpe_30d,
            )
            for a in allocations
        )

    def _sharpe(self, returns: list[float]) -> float:
        if len(returns) < _TWO:
            return _DEFAULT_SHARPE
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** _TWO for r in returns) / (len(returns) - 1)
        std = math.sqrt(variance)
        if std < _EPSILON:
            return _DEFAULT_SHARPE
        # Annualise by 24/7 minutes: 525600
        minutes_per_year = float(self._params.get("metrics.minutes_per_year"))
        return (mean / std) * math.sqrt(minutes_per_year)
