"""Tests for LiveRunner — the Phase 8 dry-run tick loop."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

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
from app.services.alerter import Alerter
from app.services.decision_audit import DecisionAuditService
from app.services.live_runner import LiveRunner
from app.services.runner_state import RunnerStateService


class _StubStrategy:
    """Minimal strategy stub: returns a pre-baked order list every tick."""

    name = "stub"

    def __init__(self, orders: list[Order]) -> None:
        self._orders = orders

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        del state, params
        return self._orders


async def _make_profile(db_session: AsyncSession) -> StrategyProfile:
    profile = StrategyProfile(name="live-runner-test", version=1, is_active=False, config={})
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
    alerter: Alerter | AsyncMock | None = None,
    runner_state: RunnerStateService | None = None,
) -> tuple[LiveRunner, PaperExchange, AsyncMock]:
    paper = PaperExchange(venue="binance", params=params, initial_cash=initial_cash)
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
    # AsyncMock(spec=Alerter) keeps test isolation tight — every test gets a
    # fresh mock so call counts don't leak across cases.
    resolved_alerter = alerter if alerter is not None else AsyncMock(spec=Alerter)
    runner = LiveRunner(
        exchanges=exchanges,
        strategy=strategy,
        oms=oms,
        audit_service=DecisionAuditService(db_session),
        params=params,
        drawdown_brake=DrawdownBrake(params=params),
        alerter=resolved_alerter,
        venue="binance",
        symbols=["BTCUSDT"],
        profile_id=profile.id,
        profile_version=profile.version,
        profile_hash="abc",
        runner_state=runner_state,
    )
    return runner, paper, resolved_alerter


@pytest.mark.asyncio
async def test_skips_when_disabled(db_session: AsyncSession) -> None:
    profile = await _make_profile(db_session)
    # live.enabled defaults to False → tick is a no-op.
    params = ProfileParams(profile={})
    runner, _, _ = _build_runner(
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
            venue="binance",
            symbol="BTCUSDT",
            product="spot",
            side="buy",
            qty_base=0.01,
            order_type="market",
        ),
        Order(
            venue="binance",
            symbol="BTCUSDT",
            product="perp",
            side="sell",
            qty_base=0.01,
            order_type="market",
        ),
    ]
    runner, _, _ = _build_runner(
        db_session=db_session,
        params=params,
        strategy=_StubStrategy(orders),
        profile=profile,
    )

    result = await runner.run_one_tick()

    assert result["status"] == "ok"
    # Two fills (spot + perp) recorded in the most recent order audit row.
    audit_rows = (
        (
            await db_session.execute(
                select(DecisionAuditEntry)
                .where(DecisionAuditEntry.decision_type == "order")
                .order_by(DecisionAuditEntry.ts.desc())
                .limit(1)
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert len(audit_rows[0].fills) == 2


@pytest.mark.asyncio
async def test_skips_dispatch_when_no_orders(db_session: AsyncSession) -> None:
    profile = await _make_profile(db_session)
    params = ProfileParams(profile={"live": {"enabled": True}})
    runner, _, _ = _build_runner(
        db_session=db_session,
        params=params,
        strategy=_StubStrategy([]),
        profile=profile,
    )

    result = await runner.run_one_tick()

    assert result["status"] == "no_orders"
    # No "order" audit row written when the strategy emits nothing.
    audit_rows = (
        (
            await db_session.execute(
                select(DecisionAuditEntry).where(DecisionAuditEntry.decision_type == "order")
            )
        )
        .scalars()
        .all()
    )
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
    runner, _, _ = _build_runner(
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
        (
            await db_session.execute(
                select(DecisionAuditEntry).where(DecisionAuditEntry.decision_type == "snapshot")
            )
        )
        .scalars()
        .all()
    )
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
    runner, _, _ = _build_runner(
        db_session=db_session,
        params=params,
        strategy=_StubStrategy([]),
        profile=profile,
    )

    await runner.run_one_tick()

    snapshot_rows = (
        (
            await db_session.execute(
                select(DecisionAuditEntry).where(DecisionAuditEntry.decision_type == "snapshot")
            )
        )
        .scalars()
        .all()
    )
    assert len(snapshot_rows) >= 1
    assert snapshot_rows[0].input_state["status"] == "ok"


@pytest.mark.asyncio
async def test_runner_alerts_on_drawdown_brake(db_session: AsyncSession) -> None:
    """When the drawdown brake fires, Alerter.send is called with critical+event."""
    profile = await _make_profile(db_session)
    # Same fixture as test_halts_on_drawdown_brake — 20% drawdown trips the
    # 5% trigger; the runner must alert before re-raising.
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
    alerter = AsyncMock(spec=Alerter)
    runner, _, _ = _build_runner(
        db_session=db_session,
        params=params,
        strategy=_StubStrategy([]),
        profile=profile,
        initial_cash=8_000.0,
        alerter=alerter,
    )

    with pytest.raises(DrawdownBrakeHalt):
        await runner.run_one_tick()

    # At least one alerter.send call with the documented severity + event.
    assert alerter.send.await_count >= 1
    critical_calls = [
        c
        for c in alerter.send.await_args_list
        if c.kwargs.get("severity") == "critical" and c.kwargs.get("event") == "DrawdownBrakeHalt"
    ]
    assert len(critical_calls) == 1
    assert "equity" in critical_calls[0].kwargs["details"]
    assert "peak" in critical_calls[0].kwargs["details"]


@pytest.mark.asyncio
async def test_runner_hydrates_peak_from_state(db_session: AsyncSession) -> None:
    """``hydrate()`` seeds the brake from the persisted ``peak_equity`` row."""
    profile = await _make_profile(db_session)
    state_svc = RunnerStateService(db_session)
    await state_svc.set("peak_equity", {"value": 12_345.67, "ts_ms": 999})
    params = ProfileParams(profile={"live": {"enabled": True}})
    runner, _, _ = _build_runner(
        db_session=db_session,
        params=params,
        strategy=_StubStrategy([]),
        profile=profile,
        runner_state=state_svc,
    )

    await runner.hydrate()

    assert runner._brake.peak == 12_345.67


@pytest.mark.asyncio
async def test_runner_populates_realized_vols(db_session: AsyncSession) -> None:
    """After multiple ticks, snapshot.realized_vols has a >0 entry for the traded symbol.

    HP7: the runner owns a ``RollingVolEstimator`` and must record each tick's
    spot close + inject the resulting per-symbol annualised vol into the
    snapshot the strategy sees. Five ticks at oscillating prices is enough to
    produce a non-zero sample stdev (window is 30 bars, but the estimator
    starts emitting at >= 3 closes).
    """
    profile = await _make_profile(db_session)
    params = ProfileParams(profile={"live": {"enabled": True}})
    captured: dict[str, dict[tuple[str, str], float]] = {}

    class _CapturingStrategy:
        name = "capture"

        def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
            del params
            captured["last"] = dict(state.snapshot.realized_vols)
            return []

    strategy = _CapturingStrategy()
    runner, paper, _ = _build_runner(
        db_session=db_session,
        params=params,
        strategy=strategy,  # type: ignore[arg-type]
        profile=profile,
    )

    # Five distinct closes => four log-returns => non-degenerate sample stdev.
    for px in (60_000.0, 60_500.0, 60_200.0, 60_800.0, 60_400.0):
        paper.set_mark_price("BTCUSDT", "spot", px)
        paper.set_mark_price("BTCUSDT", "perp", px)
        await runner.run_one_tick()

    realized = captured["last"]
    assert ("binance", "BTCUSDT") in realized
    assert realized[("binance", "BTCUSDT")] > 0.0


@pytest.mark.asyncio
async def test_runner_persists_new_peak(db_session: AsyncSession) -> None:
    """Tick that ratchets the peak writes back to ``runner_state.peak_equity``."""
    profile = await _make_profile(db_session)
    state_svc = RunnerStateService(db_session)
    # initial_cash 10_000 + zero positions → equity 10_000, fresh peak.
    params = ProfileParams(profile={"live": {"enabled": True}})
    runner, _, _ = _build_runner(
        db_session=db_session,
        params=params,
        strategy=_StubStrategy([]),
        profile=profile,
        initial_cash=10_000.0,
        runner_state=state_svc,
    )

    await runner.run_one_tick()

    persisted = await state_svc.get("peak_equity")
    assert persisted is not None
    assert persisted["value"] == 10_000.0
    assert "ts_ms" in persisted
