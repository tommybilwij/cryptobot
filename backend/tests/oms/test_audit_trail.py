"""Tests for OMS audit trail — profile_hash locks at dispatch time."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.orders import Order
from app.backtest.state import MarketSnapshot, MarketState
from app.exchanges.paper import PaperExchange
from app.models.decision_audit import DecisionAuditEntry
from app.models.strategy_profile import StrategyProfile
from app.oms.kill_switch import KillSwitch
from app.oms.ledger import MultiVenueCashLedger
from app.oms.reconciler import PositionReconciler
from app.oms.service import OMS
from app.profile.params import ProfileParams
from app.services.decision_audit import DecisionAuditService


def _hash(d: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@pytest.mark.asyncio
async def test_dispatch_writes_audit_with_provided_hash(
    db_session: AsyncSession,
) -> None:
    """Constraint #4: profile_hash + profile_version are locked at dispatch.

    Mutating ``StrategyProfile.config`` and ``StrategyProfile.version`` after
    ``OMS.dispatch()`` returns must NOT alter the audit row — six months later
    we must be able to reconstruct the exact config that produced the trade.
    """
    params = ProfileParams(profile={})
    paper = PaperExchange(venue="binance", params=params, initial_cash=10_000.0)
    paper.set_mark_price("BTCUSDT", "spot", 60000.0)

    profile = StrategyProfile(
        name="audit-trail", version=3, is_active=False, config={"x": 1}
    )
    db_session.add(profile)
    await db_session.flush()

    locked_hash = _hash({"x": 1})

    oms = OMS(
        exchanges={"binance": paper},
        audit_service=DecisionAuditService(db_session),
        params=params,
        kill_switch=KillSwitch(params=params),
        reconciler=PositionReconciler(params=params),
        ledger=MultiVenueCashLedger(),
    )
    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot",
        side="buy", qty_base=0.1, order_type="market",
    )
    result = await oms.dispatch(
        orders=[order],
        state=MarketState(
            snapshot=MarketSnapshot(ts_ms=1714521600000, bars={}),
            positions=(),
            cash_quote=10_000.0,
        ),
        strategy_name="test_strategy",
        profile_id=profile.id,
        profile_version=profile.version,
        profile_hash=locked_hash,
    )

    # Mutate the profile after dispatch — simulating a Strategy Lab edit later.
    profile.config = {"x": 9999}
    profile.version = profile.version + 1
    await db_session.flush()

    # The audit row must still reflect the OLD hash + version.
    row = (
        await db_session.execute(
            select(DecisionAuditEntry).where(
                DecisionAuditEntry.id == result.audit_entry_id
            )
        )
    ).scalar_one()
    assert row.profile_hash == locked_hash
    assert row.profile_version == 3
