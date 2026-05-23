"""ProfileService — orchestrates validation, persistence, and apply mechanics."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile
from app.profile.apply import apply_profile, get_active_profile_config
from app.repositories.strategy_profile import StrategyProfileRepository
from app.schemas.strategy_profile import StrategyProfileConfig


class ProfileService:
    """High-level operations on strategy profiles.

    Validates JSONB via Pydantic on save; persists via the repository;
    coordinates the atomic apply via profile.apply.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = StrategyProfileRepository(session)

    async def create(
        self, *, name: str, config: dict[str, Any], description: str | None = None
    ) -> StrategyProfile:
        StrategyProfileConfig.model_validate(config)  # raises ValidationError on failure
        return await self._repo.create(name=name, config=config, description=description)

    async def get(self, profile_id: uuid.UUID) -> StrategyProfile | None:
        return await self._repo.get(profile_id)

    async def list_all(self) -> list[StrategyProfile]:
        return await self._repo.list_all()

    async def list_by_name(self, name: str) -> list[StrategyProfile]:
        return await self._repo.list_by_name(name)

    async def get_active(self) -> StrategyProfile | None:
        return await self._repo.get_active()

    async def get_active_config(self) -> dict[str, Any]:
        return await get_active_profile_config(self._session)

    async def apply(self, profile_id: uuid.UUID) -> StrategyProfile:
        return await apply_profile(self._session, profile_id)

    async def clone(
        self, profile_id: uuid.UUID, *, new_name: str
    ) -> StrategyProfile:
        source = await self._repo.get(profile_id)
        if source is None:
            raise LookupError(f"strategy profile {profile_id} not found")
        return await self._repo.create(
            name=new_name, config=dict(source.config), description=source.description
        )
