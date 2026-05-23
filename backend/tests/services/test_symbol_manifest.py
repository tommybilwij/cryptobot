"""Tests for SymbolManifestService."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.symbol_manifest import SymbolManifestService


@pytest.mark.asyncio
async def test_snapshot_creates_row(db_session: AsyncSession) -> None:
    svc = SymbolManifestService(db_session)
    snapshot = await svc.snapshot(
        snapshot_date=date(2026, 5, 24),
        exchange="binance",
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    )
    await db_session.flush()
    assert snapshot.id is not None
    assert snapshot.symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


@pytest.mark.asyncio
async def test_get_returns_snapshot_for_date(db_session: AsyncSession) -> None:
    svc = SymbolManifestService(db_session)
    await svc.snapshot(
        snapshot_date=date(2026, 5, 24),
        exchange="binance",
        symbols=["BTCUSDT", "ETHUSDT"],
    )
    await db_session.flush()
    result = await svc.get(date(2026, 5, 24), exchange="binance")
    assert result is not None
    assert "ETHUSDT" in result.symbols


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(db_session: AsyncSession) -> None:
    svc = SymbolManifestService(db_session)
    result = await svc.get(date(2030, 1, 1), exchange="binance")
    assert result is None
