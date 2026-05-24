"""Worker job — drives the LiveRunner loop.

Loads the active StrategyProfile, builds the Phase 8 dependency graph
(Exchange adapters + OMS + LiveRunner) from registry values only, and runs
the loop until ``stop()`` or the drawdown brake halts.

Phase 9: adapters are built via ``exchange_factory.build_exchange`` which
returns a real venue adapter when env keys are present and dry-run is off,
or a ``PaperExchange`` otherwise. Webhook alerts on halt classes / heartbeats
are wired through an ``Alerter`` sharing the same ``RetryingFetcher``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx
from sqlalchemy import select

from app.config import settings
from app.deps import get_session_factory
from app.exchanges.base import Exchange
from app.market_data._http import RetryingFetcher
from app.models.strategy_profile import StrategyProfile
from app.oms.kill_switch import KillSwitch
from app.oms.ledger import MultiVenueCashLedger
from app.oms.reconciler import PositionReconciler
from app.oms.service import OMS
from app.profile.params import ProfileParams
from app.risk.drawdown_brake import DrawdownBrake
from app.services.alerter import Alerter
from app.services.decision_audit import DecisionAuditService
from app.services.exchange_factory import build_exchange
from app.services.live_runner import LiveRunner
from app.strategies.funding_arb import FundingArbStrategy

logger = logging.getLogger(__name__)

_VENUES: tuple[str, ...] = ("binance", "bybit", "hyperliquid")


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
        dry_run = bool(params.get("live.dry_run_mode"))

        # Shared HTTP client for the entire run — both the factory-built
        # adapters and the Alerter draw their RetryingFetcher from it. The
        # ``async with`` scope must enclose ``runner.run()`` so the fetcher
        # remains live for the duration of the loop.
        async with httpx.AsyncClient() as http_client:
            fetcher = RetryingFetcher(client=http_client, base_backoff_s=0.0)
            exchanges: dict[str, Exchange] = {
                v: build_exchange(
                    v,
                    params=params,
                    fetcher=fetcher,
                    settings=settings,
                    dry_run=dry_run,
                )
                for v in _VENUES
            }
            alerter = Alerter(params=params, fetcher=fetcher)
            # Phase 12: FundingArbStrategy now takes a list of symbols.
            # Future phase will read ``strategies.funding_arb.symbols`` from
            # the registry; for now we wrap the existing default key.
            strategy = FundingArbStrategy(venue=venue, symbols=[symbol])
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
                alerter=alerter,
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
                    "dry_run": dry_run,
                },
            )
            await runner.run()
