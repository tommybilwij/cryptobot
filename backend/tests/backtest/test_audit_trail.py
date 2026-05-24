"""Tests for backtest audit trail — profile_hash must be sha256 of params at creation."""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.backtest_run import BacktestRun
from app.models.strategy_profile import StrategyProfile


def _canonical_hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.asyncio
async def test_profile_hash_locks_at_creation(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    profile = StrategyProfile(name="audit-test", version=1, is_active=False, config={"x": 1})
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    body = {
        "profile_id": str(profile.id),
        "strategy_name": "buy_and_hold",
        "start_ts": "2024-01-01T00:00:00Z",
        "end_ts": "2024-01-01T00:02:00Z",
        "venue": "binance",
        "symbols": ["BTCUSDT"],
    }
    r = await async_client.post("/api/v1/backtests", json=body)
    assert r.status_code == 202
    run_id = r.json()["id"]
    expected = _canonical_hash({"x": 1})
    assert r.json()["profile_hash"] == expected

    # Mutate the profile AFTER the run is created.
    profile.config = {"x": 9999}
    profile.version = 2
    await db_session.flush()
    await db_session.commit()

    # The BacktestRun's hash MUST be unchanged.
    db_row = (
        await db_session.execute(select(BacktestRun).where(BacktestRun.id == uuid.UUID(run_id)))
    ).scalar_one()
    assert db_row.profile_hash == expected
    assert db_row.profile_version == 1
