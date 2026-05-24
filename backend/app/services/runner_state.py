"""RunnerStateService — get/set runner state by key (upsert semantics)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runner_state import RunnerState


class RunnerStateService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(RunnerState).where(RunnerState.key == key)
        )
        row = result.scalar_one_or_none()
        return dict(row.value) if row is not None else None

    async def set(self, key: str, value: dict[str, Any]) -> None:
        result = await self._session.execute(
            select(RunnerState).where(RunnerState.key == key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = RunnerState(key=key, value=value)
            self._session.add(row)
        else:
            row.value = value
        await self._session.flush()
