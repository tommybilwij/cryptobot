"""Tests for DecisionAuditService."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile
from app.services.decision_audit import DecisionAuditService


async def _make_profile(db_session: AsyncSession) -> StrategyProfile:
    p = StrategyProfile(name="audit-svc", version=1, is_active=False, config={})
    db_session.add(p)
    await db_session.flush()
    return p


@pytest.mark.asyncio
async def test_log_decision_creates_row(db_session: AsyncSession) -> None:
    p = await _make_profile(db_session)
    svc = DecisionAuditService(db_session)
    entry = await svc.log_decision(
        ts=datetime(2026, 5, 24, tzinfo=UTC),
        strategy_name="funding_arb",
        profile_id=p.id,
        profile_version=p.version,
        profile_hash="abc",
        input_state={"cash": 1000.0},
        orders=[{"symbol": "BTCUSDT"}],
        fills=[{"fill_px": 60000.0}],
        reconciliation_status="ok",
    )
    assert entry.id is not None
    assert entry.decision_type == "order"


@pytest.mark.asyncio
async def test_log_snapshot_creates_row_with_empty_orders(db_session: AsyncSession) -> None:
    p = await _make_profile(db_session)
    svc = DecisionAuditService(db_session)
    entry = await svc.log_snapshot(
        ts=datetime(2026, 5, 24, tzinfo=UTC),
        strategy_name="funding_arb",
        profile_id=p.id,
        profile_version=p.version,
        profile_hash="abc",
        input_state={"cash": 1000.0},
    )
    assert entry.decision_type == "snapshot"
    assert entry.orders == []
    assert entry.fills == []


@pytest.mark.asyncio
async def test_get_recent_returns_filtered_entries(db_session: AsyncSession) -> None:
    p = await _make_profile(db_session)
    svc = DecisionAuditService(db_session)
    for _ in range(3):
        await svc.log_decision(
            ts=datetime(2026, 5, 24, tzinfo=UTC),
            strategy_name="funding_arb",
            profile_id=p.id,
            profile_version=p.version,
            profile_hash="abc",
            input_state={},
            orders=[],
            fills=[],
            reconciliation_status="ok",
        )
    entries = await svc.get_recent(limit=10, strategy_name="funding_arb")
    assert len(entries) == 3
