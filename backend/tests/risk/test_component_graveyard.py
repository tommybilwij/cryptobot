"""Tests for ComponentGraveyard."""

from __future__ import annotations

from app.risk.component_graveyard import ComponentGraveyard


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
