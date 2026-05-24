"""Tests for ICTracker."""

from __future__ import annotations

from app.risk.component_graveyard import ComponentGraveyard
from app.risk.ic_tracker import ICTracker


def test_empty_returns_zero_ic() -> None:
    t = ICTracker()
    snap = t.compute_ic("momentum_30d")
    assert snap.sample_size == 0
    assert snap.spearman_ic == 0.0


def test_positive_correlation() -> None:
    t = ICTracker()
    # Score and return are positively correlated
    for i in range(10):
        t.record(
            component="momentum_30d", score=float(i), forward_return=float(i) * 0.5, ts_ms=i * 1000
        )
    snap = t.compute_ic("momentum_30d")
    assert snap.spearman_ic > 0.9


def test_negative_correlation() -> None:
    t = ICTracker()
    for i in range(10):
        t.record(
            component="funding_yield", score=float(i), forward_return=float(-i), ts_ms=i * 1000
        )
    snap = t.compute_ic("funding_yield")
    assert snap.spearman_ic < -0.9


def test_deprecate_buries_component_below_threshold() -> None:
    t = ICTracker()
    g = ComponentGraveyard()
    # Negative correlation → IC negative → below threshold 0.02
    for i in range(10):
        t.record(component="vol", score=float(i), forward_return=float(-i), ts_ms=i * 1000)
    buried = t.deprecate_if_drifting("vol", threshold=0.02, graveyard=g)
    assert buried is True
    assert g.is_buried("vol") is True
