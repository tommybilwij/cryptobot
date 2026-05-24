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
from typing import TYPE_CHECKING

from app.risk.component_graveyard import ComponentGraveyard

if TYPE_CHECKING:
    from app.services.runner_state import RunnerStateService

_IC_TRACKER_STATE_KEY = "ic_tracker"

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
    def __init__(
        self,
        *,
        max_samples: int = 1000,
        runner_state: RunnerStateService | None = None,
    ) -> None:
        self._max_samples = max_samples
        self._records: dict[str, deque[ICRecord]] = defaultdict(lambda: deque(maxlen=max_samples))
        self._runner_state = runner_state

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

    async def persist(self) -> None:
        """Write the full record set to ``runner_state.ic_tracker``.

        Stores a flat list of records tagged by component, so the same key
        round-trips through ``hydrate()`` without per-component fan-out.
        No-op when no ``RunnerStateService`` was wired in.
        """
        if self._runner_state is None:
            return
        records: list[dict[str, float | int | str]] = []
        for component, deck in self._records.items():
            for rec in deck:
                records.append(
                    {
                        "component": component,
                        "ts_ms": rec.ts_ms,
                        "score": rec.score,
                        "forward_return": rec.forward_return,
                    }
                )
        await self._runner_state.set(_IC_TRACKER_STATE_KEY, {"records": records})

    async def hydrate(self) -> None:
        """Repopulate in-memory deques from ``runner_state.ic_tracker``.

        No-op when no service is wired in or no row exists. Existing in-memory
        records are cleared first so hydrate is idempotent across restarts.
        """
        if self._runner_state is None:
            return
        stored = await self._runner_state.get(_IC_TRACKER_STATE_KEY)
        if stored is None:
            return
        self._records = defaultdict(lambda: deque(maxlen=self._max_samples))
        for raw in stored.get("records", []):
            self._records[str(raw["component"])].append(
                ICRecord(
                    ts_ms=int(raw["ts_ms"]),
                    score=float(raw["score"]),
                    forward_return=float(raw["forward_return"]),
                )
            )


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
