"""HTTP API for backtest run orchestration.

Endpoints:

- ``POST /api/v1/backtests`` — create a pending run; computes ``profile_hash``
  from ``StrategyProfile.config`` at row creation (Constraint #4 audit lock).
- ``GET  /api/v1/backtests/{run_id}`` — fetch one run by id.
- ``GET  /api/v1/backtests`` — list recent runs with optional filters.

The worker job (``run_backtest``) picks pending rows up out-of-band and runs
them; this module never blocks on engine execution.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.registry import StrategyRegistry
from app.deps import get_db
from app.models.backtest_run import BacktestRun
from app.models.strategy_profile import StrategyProfile
from app.schemas.backtest import BacktestResponse, CreateBacktestRequest

router = APIRouter(prefix="/api/v1/backtests", tags=["backtests"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

_DEFAULT_LIMIT = 50


def _canonical_profile_hash(config: dict[str, Any]) -> str:
    """sha256 over a canonical (sorted-keys, no-whitespace) JSON of the config."""
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@router.post(
    "", response_model=BacktestResponse, status_code=status.HTTP_202_ACCEPTED
)
async def create_backtest(
    body: CreateBacktestRequest, db: DbSession
) -> BacktestResponse:
    # 1. Validate profile exists.
    p_result = await db.execute(
        select(StrategyProfile).where(StrategyProfile.id == body.profile_id)
    )
    profile = p_result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown profile_id"
        )

    # 2. Validate strategy name against registry.
    registry = StrategyRegistry.default()
    if body.strategy_name not in registry.names():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown strategy_name: {body.strategy_name}",
        )

    # 3. Audit-lock the profile snapshot at row creation (Constraint #4):
    #    profile_hash is computed from the config we observed *now*, not at run time.
    run = BacktestRun(
        profile_id=profile.id,
        profile_version=profile.version,
        profile_hash=_canonical_profile_hash(profile.config),
        strategy_name=body.strategy_name,
        venue=body.venue,
        symbols=body.symbols,
        start_ts=body.start_ts,
        end_ts=body.end_ts,
        status="pending",
    )
    db.add(run)
    await db.flush()
    await db.commit()
    await db.refresh(run)
    return BacktestResponse.model_validate(run, from_attributes=True)


@router.get("/{run_id}", response_model=BacktestResponse)
async def get_backtest(run_id: uuid.UUID, db: DbSession) -> BacktestResponse:
    result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "backtest run not found")
    return BacktestResponse.model_validate(row, from_attributes=True)


@router.get("", response_model=list[BacktestResponse])
async def list_backtests(
    db: DbSession,
    limit: int = _DEFAULT_LIMIT,
    profile_id: uuid.UUID | None = None,
    strategy_name: str | None = None,
    status_filter: str | None = None,
) -> list[BacktestResponse]:
    stmt = select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(limit)
    if profile_id is not None:
        stmt = stmt.where(BacktestRun.profile_id == profile_id)
    if strategy_name is not None:
        stmt = stmt.where(BacktestRun.strategy_name == strategy_name)
    if status_filter is not None:
        stmt = stmt.where(BacktestRun.status == status_filter)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return [
        BacktestResponse.model_validate(r, from_attributes=True) for r in rows
    ]
