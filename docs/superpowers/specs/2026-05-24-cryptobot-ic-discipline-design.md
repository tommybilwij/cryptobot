# Cryptobot Phase 16 — IC Discipline + Drift Monitor Design Spec

**Date**: 2026-05-24
**Phase**: 16

## Goal

**Information Coefficient (IC) tracking** for the scoring engine's components: measures predictive power (rank correlation between score-at-time-T and return-at-time-T+k). Components with IC drifting below threshold get auto-deprecated to a graveyard. Pattern: stockbot's `live_ic_tracker.py` + `component_graveyard.py`.

## Architecture

`backend/app/risk/ic_tracker.py`:

```python
@dataclass(frozen=True)
class ICSnapshot:
    component_name: str
    ts_ms: int
    sample_size: int
    spearman_ic: float
    rolling_30d_ic: float

class ICTracker:
    """Records (component, score, forward_return) tuples; computes rolling rank corr."""

    def record(self, *, component: str, score: float, forward_return: float, ts_ms: int) -> None: ...
    def compute_ic(self, component: str, window_ms: int) -> ICSnapshot: ...
    def deprecate_if_drifting(self, component: str, threshold: float) -> bool: ...
```

`backend/app/risk/component_graveyard.py`:

```python
class ComponentGraveyard:
    """Components below IC threshold get added; ScoringEngine skips them."""

    def add(self, component: str, reason: str) -> None: ...
    def is_buried(self, component: str) -> bool: ...
    def list(self) -> tuple[str, ...]: ...
```

Both backed by **in-memory state** for Phase 16. DB persistence comes Phase 17+ if needed.

`ScoringEngine` modified: skip components in `graveyard.is_buried(name)`.

## Components

- `backend/app/risk/ic_tracker.py` — `ICTracker` + Spearman rank corr (scipy or hand-rolled)
- `backend/app/risk/component_graveyard.py` — in-memory set
- `backend/app/services/scoring.py` — accepts optional `graveyard` parameter
- `backend/tests/risk/test_ic_tracker.py` — 4 tests
- `backend/tests/risk/test_component_graveyard.py` — 3 tests
- `backend/tests/services/test_scoring.py` — append 1 test for graveyard skip

## DoD

~280 tests. IC tracking works on synthetic data. Graveyard skips components in scoring.
