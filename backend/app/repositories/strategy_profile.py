"""Repository layer for StrategyProfile (DB queries only — no business logic)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile


class StrategyProfileRepository:
    """Async DB queries for the strategy_profiles table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, profile_id: uuid.UUID) -> StrategyProfile | None:
        return (
            await self._session.execute(
                select(StrategyProfile).where(StrategyProfile.id == profile_id)
            )
        ).scalar_one_or_none()

    async def list_all(self) -> list[StrategyProfile]:
        result = await self._session.execute(
            select(StrategyProfile).order_by(StrategyProfile.updated_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_name(self, name: str) -> list[StrategyProfile]:
        result = await self._session.execute(
            select(StrategyProfile)
            .where(StrategyProfile.name == name)
            .order_by(StrategyProfile.version.desc())
        )
        return list(result.scalars().all())

    async def get_active(self) -> StrategyProfile | None:
        return (
            await self._session.execute(select(StrategyProfile).where(StrategyProfile.is_active))
        ).scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        config: dict[str, Any],
        description: str | None = None,
    ) -> StrategyProfile:
        prior_versions = await self.list_by_name(name)
        next_version = (prior_versions[0].version + 1) if prior_versions else 1
        profile = StrategyProfile(
            name=name,
            description=description,
            config=config,
            version=next_version,
            is_active=False,
        )
        self._session.add(profile)
        await self._session.flush()
        return profile
