"""SymbolManifestService — persists survivorship-safe symbol snapshots."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.symbol_manifest_snapshot import SymbolManifestSnapshot


class SymbolManifestService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def snapshot(
        self,
        *,
        snapshot_date: date,
        exchange: str,
        symbols: list[str],
    ) -> SymbolManifestSnapshot:
        row = SymbolManifestSnapshot(
            snapshot_date=snapshot_date,
            exchange=exchange,
            symbols=symbols,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(
        self, snapshot_date: date, *, exchange: str
    ) -> SymbolManifestSnapshot | None:
        result = await self._session.execute(
            select(SymbolManifestSnapshot)
            .where(SymbolManifestSnapshot.snapshot_date == snapshot_date)
            .where(SymbolManifestSnapshot.exchange == exchange)
        )
        return result.scalar_one_or_none()
