"""Load named profile fixtures from `profiles/` into the DB."""

from __future__ import annotations

import json
import pathlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.strategy_profile import StrategyProfileRepository
from app.schemas.strategy_profile import StrategyProfileConfig


async def load_fixtures(session: AsyncSession, fixtures_dir: pathlib.Path) -> int:
    """Import every `*.json` in fixtures_dir as a new profile row.

    Each fixture's filename (minus `.json`) is used as the profile name.
    Skips fixtures whose name already exists.
    """
    repo = StrategyProfileRepository(session)
    loaded = 0
    for path in sorted(fixtures_dir.glob("*.json")):
        with open(path) as f:
            config: dict[str, Any] = json.load(f)
        StrategyProfileConfig.model_validate(config)
        name = path.stem
        existing = await repo.list_by_name(name)
        if existing:
            continue
        await repo.create(
            name=name,
            config=config,
            description=config.get("meta", {}).get("description"),
        )
        loaded += 1
    await session.commit()
    return loaded
