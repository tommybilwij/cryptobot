"""Tests for RunnerStateService."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.runner_state import RunnerStateService


@pytest.mark.asyncio
async def test_get_missing_returns_none(db_session: AsyncSession) -> None:
    svc = RunnerStateService(db_session)
    result = await svc.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_set_then_get(db_session: AsyncSession) -> None:
    svc = RunnerStateService(db_session)
    await svc.set("peak_equity", {"value": 10042.15, "ts_ms": 12345})
    result = await svc.get("peak_equity")
    assert result == {"value": 10042.15, "ts_ms": 12345}


@pytest.mark.asyncio
async def test_set_overwrites_existing(db_session: AsyncSession) -> None:
    svc = RunnerStateService(db_session)
    await svc.set("foo", {"a": 1})
    await svc.set("foo", {"a": 2})
    result = await svc.get("foo")
    assert result == {"a": 2}
