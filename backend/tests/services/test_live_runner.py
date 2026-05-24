"""Tests for LiveRunner — the Phase 8 dry-run tick loop."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.orders import Order
from app.backtest.state import MarketState
from app.exchanges.paper import PaperExchange
from app.models.decision_audit import DecisionAuditEntry
from app.models.strategy_profile import StrategyProfile
from app.oms.kill_switch import KillSwitch
from app.oms.ledger import MultiVenueCashLedger
from app.oms.reconciler import PositionReconciler
from app.oms.service import OMS
from app.profile.params import ProfileParams
from app.risk.drawdown_brake import DrawdownBrake
from app.risk.exceptions import DrawdownBrakeHalt
from app.services.decision_audit import DecisionAuditService
from app.services.live_runner import LiveRunner


class _StubStrategy:
    """Minimal strategy stub: returns a pre-baked order list every tick."""

    name = "stub"

    def __init__(self, orders: list[Order]) -> None:
        self._orders = orders

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        del state, params
        return self._orders


async def _make_profile(db_session: AsyncSession) -> StrategyProfile:
    profile = StrategyProfile(
        name="live-runner-test", version=1, is_active=False, config={}
    )
    db_session.add(profile)
    await db_session.flush()
    return profile


def _build_runner(
    *,
    db_session: AsyncSession,
    params: ProfileParams,
    strategy: _StubStrategy,
    profile: StrategyProfile,
    initial_cash: float = 10_000.0,
) -> tuple[LiveRunner, PaperExchange]:
    paper = PaperExchange(
        venue="binance", params=params, initial_cash=initial_cash
    )
    paper.set_mark_price("BTCUSDT", "spot", 60_000.0)
    paper.set_mark_price("BTCUSDT", "perp", 60_000.0)
    exchanges: dict[str, Any] = {"binance": paper}
    oms = OMS(
        exchanges=exchanges,
        audit_service=DecisionAuditService(db_session),
        params=params,
        kill_switch=KillSwitch(params=params),
        reconciler=PositionReconciler(params=params),
        ledger=MultiVenueCashLedger(),
    )
    runner = LiveRunner(
        exchanges=exchanges,
        strategy=strategy,
        oms=oms,
        audit_service=DecisionAuditService(db_session),
        params=params,
        drawdown_brake=DrawdownBrake(params=params),
        venue="binance",
        symbols=["BTCUSDT"],
        profile_id=profile.id,
        profile_version=profile.version,
        profile_hash="abc",
    )
    return runner, paper


@pytest.mark.asyncio
async def test_skips_when_disabled(db_session: AsyncSession) -> None:
    profile = await _make_profile(db_session)
    # live.enabled defaults to False → tick is a no-op.
    params = ProfileParams(profile={})
    runner, _ = _build_runner(
        db_session=db_session,
        params=params,
        strategy=_StubStrategy([]),
        profile=profile,
    )

    result = await runner.run_one_tick()

    assert result == {"status": "disabled"}


@pytest.mark.asyncio
async def test_dispatches_when_strategy_emits_orders(
    db_session: AsyncSession,
) -> None:
    profile = await _make_profile(db_session)
    params = ProfileParams(profile={"live": {"enabled": True}})
    orders = [
        Order(
            venue="binance", symbol="BTCUSDT", product="spot",
            side="buy", qty_base=0.01, order_type="market",
        ),
        Order(
            venue="binance", symbol="BTCUSDT", product="perp",
            side="sell", qty_base=0.01, order_type="market",
        ),
    ]
    runner, _ = _build_runner(
        db_session=db_session,
        params=params,
        strategy=_StubStrategy(orders),
        profile=profile,
    )

    result = await runner.run_one_tick()

    assert result["status"] == "ok"
    # Two fills (spot + perp) recorded in the most recent order audit row.
    audit_rows = (
        await db_session.execute(
            select(DecisionAuditEntry)
            .where(DecisionAuditEntry.decision_type == "order")
            .order_by(DecisionAuditEntry.ts.desc())
            .limit(1)
        )
    ).scalars().all()
    assert len(audit_rows) == 1
    assert len(audit_rows[0].fills) == 2


@pytest.mark.asyncio
async def test_skips_dispatch_when_no_orders(db_session: AsyncSession) -> None:
    profile = await _make_profile(db_session)
    params = ProfileParams(profile={"live": {"enabled": True}})
    runner, _ = _build_runner(
        db_session=db_session,
        params=params,
        strategy=_StubStrategy([]),
        profile=profile,
    )

    result = await runner.run_one_tick()

    assert result["status"] == "no_orders"
    # No "order" audit row written when the strategy emits nothing.
    audit_rows = (
        await db_session.execute(
            select(DecisionAuditEntry).where(
                DecisionAuditEntry.decision_type == "order"
            )
        )
    ).scalars().all()
    assert audit_rows == []


@pytest.mark.asyncio
async def test_halts_on_drawdown_brake(db_session: AsyncSession) -> None:
    profile = await _make_profile(db_session)
    # Seed peak at 10_000; paper cash 8_000 → 20% drawdown, well past 5%.
    params = ProfileParams(
        profile={
            "live": {"enabled": True},
            "risk": {
                "drawdown_brake": {
                    "peak_equity": 10_000.0,
                    "trigger_pct": 0.05,
                }
            },
        }
    )
    runner, _ = _build_runner(
        db_session=db_session,
        params=params,
        strategy=_StubStrategy([]),
        profile=profile,
        initial_cash=8_000.0,
    )

    with pytest.raises(DrawdownBrakeHalt):
        await runner.run_one_tick()

    # A snapshot row with the halt status was logged before the raise.
    snapshot_rows = (
        await db_session.execute(
            select(DecisionAuditEntry).where(
                DecisionAuditEntry.decision_type == "snapshot"
            )
        )
    ).scalars().all()
    assert len(snapshot_rows) == 1
    assert snapshot_rows[0].input_state["status"] == "halted_drawdown_brake"


@pytest.mark.asyncio
async def test_logs_snapshot_after_interval(db_session: AsyncSession) -> None:
    profile = await _make_profile(db_session)
    # snapshot_interval_s=0.0 → every tick emits a heartbeat snapshot.
    params = ProfileParams(
        profile={
            "live": {"enabled": True, "snapshot_interval_s": 0.0},
        }
    )
    runner, _ = _build_runner(
        db_session=db_session,
        params=params,
        strategy=_StubStrategy([]),
        profile=profile,
    )

    await runner.run_one_tick()

    snapshot_rows = (
        await db_session.execute(
            select(DecisionAuditEntry).where(
                DecisionAuditEntry.decision_type == "snapshot"
            )
        )
    ).scalars().all()
    assert len(snapshot_rows) >= 1
    assert snapshot_rows[0].input_state["status"] == "ok"
