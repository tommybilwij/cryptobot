"""Tests for UniverseLoader."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.symbol_manifest_snapshot import SymbolManifestSnapshot
from app.services.universe_loader import UniverseLoader


@pytest.mark.asyncio
async def test_missing_snapshot_returns_empty(db_session: AsyncSession) -> None:
    """No snapshot row -> empty list (caller decides how to handle)."""
    loader = UniverseLoader(db_session)
    result = await loader.for_date(snapshot_date=date(2026, 1, 1), exchange="binance")
    assert result == []


@pytest.mark.asyncio
async def test_loads_symbols_from_snapshot(db_session: AsyncSession) -> None:
    """Existing snapshot -> its symbol list."""
    snap = SymbolManifestSnapshot(
        snapshot_date=date(2026, 5, 24),
        exchange="binance",
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    )
    db_session.add(snap)
    await db_session.flush()

    loader = UniverseLoader(db_session)
    result = await loader.for_date(snapshot_date=date(2026, 5, 24), exchange="binance")
    assert set(result) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}


@pytest.mark.asyncio
async def test_different_exchange_returns_empty(db_session: AsyncSession) -> None:
    """Snapshot scoped to exchange — looking up a different venue -> empty."""
    snap = SymbolManifestSnapshot(
        snapshot_date=date(2026, 5, 24),
        exchange="binance",
        symbols=["BTCUSDT"],
    )
    db_session.add(snap)
    await db_session.flush()

    loader = UniverseLoader(db_session)
    result = await loader.for_date(snapshot_date=date(2026, 5, 24), exchange="bybit")
    assert result == []
