"""Prometheus metrics endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.models.backtest_run import BacktestRun
from app.models.decision_audit import DecisionAuditEntry
from app.models.strategy_profile import StrategyProfile
from app.profile.params import ProfileParams

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_class=Response)
async def metrics(db: DbSession) -> Response:
    decision_count = (
        await db.execute(select(func.count()).select_from(DecisionAuditEntry))
    ).scalar() or 0
    backtest_count = (
        await db.execute(select(func.count()).select_from(BacktestRun))
    ).scalar() or 0
    active = (
        await db.execute(
            select(StrategyProfile).where(StrategyProfile.is_active.is_(True))
        )
    ).scalar_one_or_none()
    kill_switch = 0
    if active is not None:
        params = ProfileParams(profile=active.config)
        kill_switch = 1 if bool(params.get("oms.kill_switch_active")) else 0

    lines = [
        "# HELP cryptobot_up 1 if the API is responding",
        "# TYPE cryptobot_up gauge",
        "cryptobot_up 1",
        "# HELP cryptobot_decision_audit_total Count of DecisionAuditEntry rows",
        "# TYPE cryptobot_decision_audit_total counter",
        f"cryptobot_decision_audit_total {decision_count}",
        "# HELP cryptobot_backtest_runs_total Count of BacktestRun rows",
        "# TYPE cryptobot_backtest_runs_total counter",
        f"cryptobot_backtest_runs_total {backtest_count}",
        "# HELP cryptobot_oms_kill_switch_active 1 if kill switch is set",
        "# TYPE cryptobot_oms_kill_switch_active gauge",
        f"cryptobot_oms_kill_switch_active {kill_switch}",
    ]
    return Response(content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
