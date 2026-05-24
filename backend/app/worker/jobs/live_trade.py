"""Worker job — drives the LiveRunner loop.

Loads the active StrategyProfile, builds the Phase 8 dependency graph
(PaperExchange + OMS + LiveRunner) from registry values only, and runs
the loop until ``stop()`` or the drawdown brake halts.

Phase 8 is dry-run only — ``PaperExchange`` is wired unconditionally.
Real venue adapters land in Phase 9 once dry-run validates over days.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import select

from app.deps import get_session_factory
from app.exchanges.base import Exchange
from app.exchanges.paper import PaperExchange
from app.models.strategy_profile import StrategyProfile
from app.oms.kill_switch import KillSwitch
from app.oms.ledger import MultiVenueCashLedger
from app.oms.reconciler import PositionReconciler
from app.oms.service import OMS
from app.profile.params import ProfileParams
from app.risk.drawdown_brake import DrawdownBrake
from app.services.decision_audit import DecisionAuditService
from app.services.live_runner import LiveRunner
from app.strategies.funding_arb import FundingArbStrategy

logger = logging.getLogger(__name__)

_DEFAULT_INITIAL_CASH = 10_000.0


def _hash(d: dict[str, Any]) -> str:
    """Stable sha256 of a profile config blob (sorted keys, compact separators)."""
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def run() -> None:
    """Entry point invoked by ``worker.main`` when ``WORKER_JOB=live_trade``.

    Raises:
        KeyError: If there is no active StrategyProfile in the DB.
    """
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(StrategyProfile).where(StrategyProfile.is_active.is_(True))
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise KeyError("no active profile; cannot start live runner")

        params = ProfileParams(profile=profile.config)
        venue = str(params.get("live.venue"))
        symbol = str(params.get("strategies.funding_arb.default_symbol"))
        exchanges: dict[str, Exchange] = {
            venue: PaperExchange(
                venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH
            )
        }
        strategy = FundingArbStrategy(venue=venue, symbol=symbol)
        oms = OMS(
            exchanges=exchanges,
            audit_service=DecisionAuditService(session),
            params=params,
            kill_switch=KillSwitch(params=params),
            reconciler=PositionReconciler(params=params),
            ledger=MultiVenueCashLedger(),
        )
        runner = LiveRunner(
            exchanges=exchanges,
            strategy=strategy,
            oms=oms,
            audit_service=DecisionAuditService(session),
            params=params,
            drawdown_brake=DrawdownBrake(params=params),
            venue=venue,
            symbols=[symbol],
            profile_id=profile.id,
            profile_version=profile.version,
            profile_hash=_hash(profile.config),
        )
        logger.info(
            "live_trade starting",
            extra={
                "profile_id": str(profile.id),
                "profile_version": profile.version,
                "venue": venue,
                "symbol": symbol,
            },
        )
        await runner.run()
