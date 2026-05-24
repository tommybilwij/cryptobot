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
from app.services.metrics_collector import collector

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

# p95 over the latency ring buffer — index-based approximation.
_P95 = 0.95


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
        "# HELP cryptobot_dispatch_total Total dispatch attempts",
        "# TYPE cryptobot_dispatch_total counter",
        f"cryptobot_dispatch_total {collector.dispatch_count}",
        "# HELP cryptobot_dispatch_failures_total Total dispatch failures",
        "# TYPE cryptobot_dispatch_failures_total counter",
        f"cryptobot_dispatch_failures_total {collector.dispatch_failures}",
        "# HELP cryptobot_fills_total Total fills recorded",
        "# TYPE cryptobot_fills_total counter",
        f"cryptobot_fills_total {collector.fills_total}",
        "# HELP cryptobot_fills_partial_total Total partially-filled fills",
        "# TYPE cryptobot_fills_partial_total counter",
        f"cryptobot_fills_partial_total {collector.fills_partial}",
        "# HELP cryptobot_halts_total Halts by class",
        "# TYPE cryptobot_halts_total counter",
    ]
    for halt_class, count in collector.halts.items():
        lines.append(f'cryptobot_halts_total{{class="{halt_class}"}} {count}')
    lines.extend(
        [
            "# HELP cryptobot_venue_errors_total Venue/adapter errors by venue",
            "# TYPE cryptobot_venue_errors_total counter",
        ]
    )
    for venue, count in collector.venue_errors.items():
        lines.append(f'cryptobot_venue_errors_total{{venue="{venue}"}} {count}')

    latencies = sorted(collector.dispatch_latencies_ms)
    p95 = latencies[int(len(latencies) * _P95)] if latencies else 0.0
    lines.extend(
        [
            "# HELP cryptobot_dispatch_latency_p95_ms Dispatch latency p95 (ms)",
            "# TYPE cryptobot_dispatch_latency_p95_ms gauge",
            f"cryptobot_dispatch_latency_p95_ms {p95}",
        ]
    )
    return Response(content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
