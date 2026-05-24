"""HTTP API for OMS state + kill switch toggle."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.models.decision_audit import DecisionAuditEntry
from app.models.strategy_profile import StrategyProfile
from app.profile.params import ProfileParams
from app.schemas.oms import KillRequest, KillResponse, OMSStatusResponse, VenueStatus

router = APIRouter(prefix="/api/v1/oms", tags=["oms"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

_VENUES: tuple[str, ...] = ("binance", "bybit", "hyperliquid")


async def _active_profile(db: AsyncSession) -> StrategyProfile | None:
    result = await db.execute(
        select(StrategyProfile).where(StrategyProfile.is_active.is_(True))
    )
    return result.scalar_one_or_none()


@router.post("/kill", response_model=KillResponse)
async def kill(body: KillRequest, db: DbSession) -> KillResponse:
    """Flip ``oms.kill_switch_active`` on the active profile, bumping its version."""
    _ = body  # reason is accepted but not stored on the profile (audit trail follows)
    profile = await _active_profile(db)
    if profile is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "no active profile to flip"
        )
    new_config = dict(profile.config) if profile.config else {}
    oms_section = dict(new_config.get("oms", {}))
    oms_section["kill_switch_active"] = True
    new_config["oms"] = oms_section
    profile.config = new_config
    profile.version = profile.version + 1
    await db.flush()
    await db.commit()
    return KillResponse(
        active_profile_id=str(profile.id),
        kill_switch_active=True,
        new_version=profile.version,
    )


@router.get("/status", response_model=OMSStatusResponse)
async def status_endpoint(db: DbSession) -> OMSStatusResponse:
    """Return current kill-switch state, last dispatch ts, and venue list."""
    profile = await _active_profile(db)
    if profile is None:
        return OMSStatusResponse(
            kill_switch_active=False,
            active_profile_id=None,
            active_profile_version=None,
            last_dispatch_ts=None,
            last_reconciliation_status=None,
            venues=[
                VenueStatus(name=v, configured=False, use_testnet=True)
                for v in _VENUES
            ],
        )
    params = ProfileParams(profile=profile.config)
    last = await db.execute(
        select(DecisionAuditEntry)
        .order_by(DecisionAuditEntry.ts.desc())
        .limit(1)
    )
    last_entry = last.scalar_one_or_none()
    return OMSStatusResponse(
        kill_switch_active=bool(params.get("oms.kill_switch_active")),
        active_profile_id=str(profile.id),
        active_profile_version=profile.version,
        last_dispatch_ts=last_entry.ts if last_entry else None,
        last_reconciliation_status=(
            last_entry.reconciliation_status if last_entry else None
        ),
        venues=[
            VenueStatus(
                name=v,
                configured=False,  # Phase 7+ will reflect env-key presence
                use_testnet=bool(params.get(f"exchanges.{v}.use_testnet")),
            )
            for v in _VENUES
        ],
    )
