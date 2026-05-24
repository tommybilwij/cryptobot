"""HTTP API for live runner state.

``GET /status`` returns the most recent equity / venue / toggle state read from
the active profile plus the latest ``DecisionAuditEntry`` row. ``POST /stop``
flips ``live.enabled`` to ``False`` on the active profile and bumps the
version — the runner loop reads the flag every tick and skips when disabled.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.models.decision_audit import DecisionAuditEntry
from app.models.strategy_profile import StrategyProfile
from app.profile.params import ProfileParams
from app.schemas.live import LiveStatusResponse, LiveStopResponse

router = APIRouter(prefix="/api/v1/live", tags=["live"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _active_profile(db: AsyncSession) -> StrategyProfile | None:
    """Return the single active StrategyProfile (or None if no row is active)."""
    result = await db.execute(
        select(StrategyProfile).where(StrategyProfile.is_active.is_(True))
    )
    return result.scalar_one_or_none()


@router.get("/status", response_model=LiveStatusResponse)
async def get_status(db: DbSession) -> LiveStatusResponse:
    """Return live toggles + last-tick state.

    When no profile is active, returns the registry defaults (which are
    safe-by-default: ``enabled=False``, ``dry_run_mode=True``).
    """
    profile = await _active_profile(db)
    config = profile.config if profile else {}
    params = ProfileParams(profile=config)
    last_q = await db.execute(
        select(DecisionAuditEntry).order_by(DecisionAuditEntry.ts.desc()).limit(1)
    )
    last_entry = last_q.scalar_one_or_none()
    peak = float(params.get("risk.drawdown_brake.peak_equity"))
    last_equity: float | None = None
    if last_entry is not None and isinstance(last_entry.input_state, dict):
        eq = last_entry.input_state.get("equity")
        if isinstance(eq, (int, float)):
            last_equity = float(eq)
    drawdown_pct: float | None = None
    if last_equity is not None and peak > 0.0:
        drawdown_pct = (last_equity - peak) / peak
    return LiveStatusResponse(
        enabled=bool(params.get("live.enabled")),
        dry_run_mode=bool(params.get("live.dry_run_mode")),
        venue=str(params.get("live.venue")),
        last_tick_ts=last_entry.ts if last_entry else None,
        last_reconciliation_status=(
            last_entry.reconciliation_status if last_entry else None
        ),
        last_equity_quote=last_equity,
        peak_equity_quote=peak,
        drawdown_pct=drawdown_pct,
    )


@router.post("/stop", response_model=LiveStopResponse)
async def stop(db: DbSession) -> LiveStopResponse:
    """Flip ``live.enabled`` to ``False`` on the active profile (bumps version).

    The runner loop reads the flag every tick — once flipped, subsequent ticks
    return ``{"status": "disabled"}`` without touching exchanges.
    """
    profile = await _active_profile(db)
    if profile is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "no active profile to stop"
        )
    new_config = dict(profile.config) if profile.config else {}
    live_section = dict(new_config.get("live", {}))
    live_section["enabled"] = False
    new_config["live"] = live_section
    profile.config = new_config
    profile.version = profile.version + 1
    await db.flush()
    await db.commit()
    return LiveStopResponse(
        active_profile_id=str(profile.id),
        live_enabled=False,
        new_version=profile.version,
    )
