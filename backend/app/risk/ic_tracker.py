"""ICTracker — Information Coefficient (Spearman rank corr) for scoring components.

Records (component, score, forward_return) tuples in memory. ``compute_ic``
returns the Spearman rank correlation over the rolling window. If IC drifts
below threshold for ``min_samples`` consecutive snapshots, ``deprecate_if_drifting``
adds the component to the graveyard.

Phase 16: pure-Python Spearman (no scipy dep). Phase 17+ may swap to a
windowed/streaming implementation if call volume grows.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass

from app.risk.component_graveyard import ComponentGraveyard

_MIN_SAMPLES_FOR_CORR = 3
_MIN_RANK_PAIRS = 2


@dataclass(frozen=True)
class ICRecord:
    ts_ms: int
    score: float
    forward_return: float


@dataclass(frozen=True)
class ICSnapshot:
    component_name: str
    ts_ms: int
    sample_size: int
    spearman_ic: float


class ICTracker:
    def __init__(self, *, max_samples: int = 1000) -> None:
        self._records: dict[str, deque[ICRecord]] = defaultdict(
            lambda: deque(maxlen=max_samples)
        )

    def record(
        self,
        *,
        component: str,
        score: float,
        forward_return: float,
        ts_ms: int,
    ) -> None:
        self._records[component].append(
            ICRecord(ts_ms=ts_ms, score=score, forward_return=forward_return)
        )

    def compute_ic(self, component: str, *, window_ms: int | None = None) -> ICSnapshot:
        records = list(self._records.get(component, []))
        if window_ms is not None and records:
            cutoff = records[-1].ts_ms - window_ms
            records = [r for r in records if r.ts_ms >= cutoff]
        n = len(records)
        if n < _MIN_SAMPLES_FOR_CORR:
            return ICSnapshot(
                component_name=component,
                ts_ms=records[-1].ts_ms if records else 0,
                sample_size=n,
                spearman_ic=0.0,
            )
        ic = _spearman_rank_corr(
            [r.score for r in records],
            [r.forward_return for r in records],
        )
        return ICSnapshot(
            component_name=component,
            ts_ms=records[-1].ts_ms,
            sample_size=n,
            spearman_ic=ic,
        )

    def deprecate_if_drifting(
        self,
        component: str,
        *,
        threshold: float,
        graveyard: ComponentGraveyard,
        window_ms: int | None = None,
    ) -> bool:
        snap = self.compute_ic(component, window_ms=window_ms)
        if snap.sample_size < _MIN_SAMPLES_FOR_CORR:
            return False
        if snap.spearman_ic < threshold:
            graveyard.add(
                component=component,
                reason=f"IC drifted to {snap.spearman_ic:.4f} below threshold {threshold:.4f}",
            )
            return True
        return False


def _spearman_rank_corr(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation. Pure-Python; no scipy dep.

    Returns 0.0 on degenerate input (n < 2 or zero variance).
    """
    n = len(xs)
    if n < _MIN_RANK_PAIRS:
        return 0.0
    rx = _ranks(xs)
    ry = _ranks(ys)
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    num = 0.0
    den_x = 0.0
    den_y = 0.0
    for i in range(n):
        dx = rx[i] - mean_x
        dy = ry[i] - mean_y
        num += dx * dy
        den_x += dx * dx
        den_y += dy * dy
    den = math.sqrt(den_x * den_y)
    if den == 0.0:
        return 0.0
    return num / den


def _ranks(values: list[float]) -> list[float]:
    """Average-rank assignment (handles ties)."""
    indexed = sorted(enumerate(values), key=lambda t: t[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks
