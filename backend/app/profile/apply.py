"""apply_profile: atomic switch of the active strategy profile.

Constraint #3 (leak-gap prevention) is enforced *at read time* via
ProfileParams, which falls back to the registry default for any key the new
active profile doesn't carry. Apply itself only flips the is_active flags;
ProfileParams does the per-key default resolution on every get().

This design means we never have to rewrite JSONB blobs at apply time — the
registry is the source of truth, and the profile is treated as a sparse
override layer.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile


class NoActiveProfile(LookupError):
    """Raised when no profile has is_active = True."""


async def apply_profile(session: AsyncSession, profile_id: uuid.UUID) -> StrategyProfile:
    """Switch the active flag from whatever is current to `profile_id`.

    Runs in a single transaction (the session's existing transaction):
      1. Verify target profile exists.
      2. Clear is_active on all rows.
      3. Set is_active on the target.
    """
    target_q = select(StrategyProfile).where(StrategyProfile.id == profile_id)
    target = (await session.execute(target_q)).scalar_one_or_none()
    if target is None:
        raise LookupError(f"strategy profile {profile_id} not found")

    await session.execute(
        update(StrategyProfile).where(StrategyProfile.is_active).values(is_active=False)
    )
    await session.execute(
        update(StrategyProfile).where(StrategyProfile.id == profile_id).values(is_active=True)
    )
    await session.flush()
    await session.refresh(target)
    return target


async def get_active_profile_config(session: AsyncSession) -> dict[str, Any]:
    """Return the active profile's JSONB config blob.

    Raises NoActiveProfile if no profile is active.
    """
    q = select(StrategyProfile).where(StrategyProfile.is_active)
    profile = (await session.execute(q)).scalar_one_or_none()
    if profile is None:
        raise NoActiveProfile("no active strategy profile")
    return dict(profile.config)
