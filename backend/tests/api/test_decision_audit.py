"""Tests for /api/v1/decision-audit endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_audit import DecisionAuditEntry
from app.models.strategy_profile import StrategyProfile


@pytest.mark.asyncio
async def test_recent_returns_entries(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    p = StrategyProfile(name="da-test", version=1, is_active=False, config={})
    db_session.add(p)
    await db_session.flush()

    entry = DecisionAuditEntry(
        ts=datetime(2026, 5, 24, tzinfo=UTC),
        strategy_name="funding_arb",
        profile_id=p.id,
        profile_version=1,
        profile_hash="abc",
        decision_type="order",
        input_state={},
        orders=[],
        fills=[],
        reconciliation_status="ok",
    )
    db_session.add(entry)
    await db_session.flush()
    await db_session.commit()

    r = await async_client.get("/api/v1/decision-audit/recent")
    assert r.status_code == 200
    assert any(e["strategy_name"] == "funding_arb" for e in r.json())


@pytest.mark.asyncio
async def test_recent_filters_by_strategy(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    p = StrategyProfile(name="da-filter", version=1, is_active=False, config={})
    db_session.add(p)
    await db_session.flush()

    for name in ("strat_a", "strat_b"):
        db_session.add(
            DecisionAuditEntry(
                ts=datetime(2026, 5, 24, tzinfo=UTC),
                strategy_name=name,
                profile_id=p.id,
                profile_version=1,
                profile_hash="x",
                decision_type="order",
                input_state={},
                orders=[],
                fills=[],
                reconciliation_status="ok",
            )
        )
    await db_session.flush()
    await db_session.commit()

    r = await async_client.get("/api/v1/decision-audit/recent?strategy_name=strat_a")
    assert r.status_code == 200
    names = {e["strategy_name"] for e in r.json()}
    assert "strat_a" in names
    assert "strat_b" not in names
