"""UniverseLoader — survivorship-safe universe load from ``SymbolManifestSnapshot``.

Backtests must run against the universe AS IT WAS at the snapshot date, not
the set of coins listed today; otherwise results are inflated by survivorship
bias (delisted coins disappear from the analysis entirely).

This loader reads ``symbol_manifest_snapshots`` and returns the symbol list for
the requested ``(snapshot_date, exchange)``. Missing snapshot -> empty list
(callers decide whether that's a hard error or a backfill trigger).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.symbol_manifest_snapshot import SymbolManifestSnapshot


class UniverseLoader:
    """Loads the survivorship-safe universe for a given backtest date."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_date(self, *, snapshot_date: date, exchange: str) -> list[str]:
        """Return the snapshot's symbols, or ``[]`` if no row exists."""
        result = await self._session.execute(
            select(SymbolManifestSnapshot)
            .where(SymbolManifestSnapshot.snapshot_date == snapshot_date)
            .where(SymbolManifestSnapshot.exchange == exchange)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return []
        return list(row.symbols)
