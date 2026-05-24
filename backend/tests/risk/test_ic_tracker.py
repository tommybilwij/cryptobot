"""Tests for ICTracker."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.risk.component_graveyard import ComponentGraveyard
from app.risk.ic_tracker import ICTracker
from app.services.runner_state import RunnerStateService


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


@pytest.mark.asyncio
async def test_persist_then_hydrate_roundtrip(db_session: AsyncSession) -> None:
    """Records survive a serialise / restart / load cycle bit-for-bit."""
    state_svc = RunnerStateService(db_session)
    src = ICTracker(runner_state=state_svc)
    for i in range(5):
        src.record(
            component="momentum_30d",
            score=float(i),
            forward_return=float(i) * 0.5,
            ts_ms=i * 1000,
        )
    src.record(component="vol", score=1.0, forward_return=-0.5, ts_ms=42)

    await src.persist()

    dst = ICTracker(runner_state=state_svc)
    await dst.hydrate()

    # Same records → same IC → same snapshot.
    src_snap = src.compute_ic("momentum_30d")
    dst_snap = dst.compute_ic("momentum_30d")
    assert dst_snap.sample_size == src_snap.sample_size
    assert dst_snap.spearman_ic == src_snap.spearman_ic
    assert dst.compute_ic("vol").sample_size == 1
