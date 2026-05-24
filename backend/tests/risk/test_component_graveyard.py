"""Tests for ComponentGraveyard."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.risk.component_graveyard import ComponentGraveyard
from app.services.runner_state import RunnerStateService


def test_empty_graveyard() -> None:
    g = ComponentGraveyard()
    assert g.is_buried("any") is False
    assert g.list() == ()


def test_add_and_check() -> None:
    g = ComponentGraveyard()
    g.add("momentum_30d", reason="IC dropped below 0.02")
    assert g.is_buried("momentum_30d") is True
    entries = g.list()
    assert len(entries) == 1
    assert entries[0].reason == "IC dropped below 0.02"


def test_revive_removes_entry() -> None:
    g = ComponentGraveyard()
    g.add("funding_yield", reason="test")
    g.revive("funding_yield")
    assert g.is_buried("funding_yield") is False


@pytest.mark.asyncio
async def test_persist_then_hydrate_roundtrip(db_session: AsyncSession) -> None:
    """Buried entries survive a serialise / restart / load cycle."""
    state_svc = RunnerStateService(db_session)
    src = ComponentGraveyard(runner_state=state_svc)
    src.add("momentum_30d", reason="IC drifted to -0.05 below threshold 0.02")
    src.add("funding_yield", reason="IC drifted to 0.001 below threshold 0.02")

    await src.persist()

    dst = ComponentGraveyard(runner_state=state_svc)
    await dst.hydrate()

    assert dst.is_buried("momentum_30d") is True
    assert dst.is_buried("funding_yield") is True
    assert {e.component for e in dst.list()} == {"momentum_30d", "funding_yield"}
