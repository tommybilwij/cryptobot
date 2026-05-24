"""Tests for apply_profile — atomic switch with leak-gap prevention."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile
from app.profile.apply import apply_profile, get_active_profile_config
from app.profile.defaults import PROFILE_SCOPED_DEFAULTS


@pytest.mark.asyncio
async def test_apply_switches_active_flag(db_session: AsyncSession) -> None:
    a = StrategyProfile(name="a", config={}, is_active=True)
    b = StrategyProfile(name="b", config={}, is_active=False)
    db_session.add_all([a, b])
    await db_session.flush()

    await apply_profile(db_session, b.id)
    await db_session.flush()

    refreshed_a = (
        await db_session.execute(select(StrategyProfile).where(StrategyProfile.id == a.id))
    ).scalar_one()
    refreshed_b = (
        await db_session.execute(select(StrategyProfile).where(StrategyProfile.id == b.id))
    ).scalar_one()
    assert refreshed_a.is_active is False
    assert refreshed_b.is_active is True


@pytest.mark.asyncio
async def test_apply_unknown_id_raises(db_session: AsyncSession) -> None:
    with pytest.raises(LookupError):
        await apply_profile(db_session, uuid.uuid4())


@pytest.mark.asyncio
async def test_apply_round_trip_a_b_a_preserves_a_values(db_session: AsyncSession) -> None:
    """Switching A -> B -> A leaves no leaked keys from B."""
    a_config = {
        "strategies": {
            "funding_arb": {"entry_bps_per_8h": 12.0},
        }
    }
    b_config = {
        "strategies": {
            "funding_arb": {"entry_bps_per_8h": 20.0},
        }
    }
    a = StrategyProfile(name="aggressive", config=a_config, is_active=True)
    b = StrategyProfile(name="more_aggressive", config=b_config, is_active=False)
    db_session.add_all([a, b])
    await db_session.flush()

    await apply_profile(db_session, b.id)
    config_after_b = await get_active_profile_config(db_session)
    assert config_after_b["strategies"]["funding_arb"]["entry_bps_per_8h"] == 20.0

    await apply_profile(db_session, a.id)
    config_after_a = await get_active_profile_config(db_session)
    assert config_after_a["strategies"]["funding_arb"]["entry_bps_per_8h"] == 12.0


@pytest.mark.asyncio
async def test_apply_resets_omitted_keys_to_defaults(db_session: AsyncSession) -> None:
    """Apply walks the registry: any path absent from the new profile resolves
    to its registry default via ProfileParams (no in-DB rewriting needed;
    ProfileParams handles fallback)."""
    from app.profile.params import ProfileParams

    a = StrategyProfile(
        name="custom",
        config={"strategies": {"funding_arb": {"entry_bps_per_8h": 50.0}}},
        is_active=True,
    )
    b = StrategyProfile(name="defaulty", config={}, is_active=False)
    db_session.add_all([a, b])
    await db_session.flush()

    await apply_profile(db_session, b.id)
    config = await get_active_profile_config(db_session)
    params = ProfileParams(config)
    # b's profile is empty, so this resolves to the registry default:
    assert (
        params.get("strategies.funding_arb.entry_bps_per_8h")
        == (PROFILE_SCOPED_DEFAULTS["strategies.funding_arb.entry_bps_per_8h"])
    )
