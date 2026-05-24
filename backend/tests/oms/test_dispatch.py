"""Tests for OMS.dispatch — happy path with paper adapters."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.orders import Order
from app.backtest.state import MarketSnapshot, MarketState
from app.exchanges.paper import PaperExchange
from app.models.strategy_profile import StrategyProfile
from app.oms.kill_switch import KillSwitch
from app.oms.ledger import MultiVenueCashLedger
from app.oms.reconciler import PositionReconciler
from app.oms.service import OMS
from app.profile.params import ProfileParams
from app.services.decision_audit import DecisionAuditService


def _state() -> MarketState:
    return MarketState(
        snapshot=MarketSnapshot(ts_ms=1714521600000, bars={}),
        positions=(),
        cash_quote=10_000.0,
    )


@pytest.mark.asyncio
async def test_dispatch_single_order_returns_fills(db_session: AsyncSession) -> None:
    params = ProfileParams(profile={})
    paper = PaperExchange(venue="binance", params=params, initial_cash=10_000.0)
    paper.set_mark_price("BTCUSDT", "spot", 60000.0)

    profile = StrategyProfile(name="oms-test", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()

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
        state=_state(),
        strategy_name="test_strategy",
        profile_id=profile.id,
        profile_version=1,
        profile_hash="abc",
    )

    assert len(result.fills) == 1
    assert result.fills[0].fill_px == pytest.approx(60030.0)
    assert result.reconciliation_status == "ok"
    assert result.audit_entry_id is not None


@pytest.mark.asyncio
async def test_dispatch_kill_switch_active_raises(db_session: AsyncSession) -> None:
    from app.oms.exceptions import KillSwitchActive

    params = ProfileParams(profile={"oms": {"kill_switch_active": True}})
    paper = PaperExchange(venue="binance", params=params, initial_cash=10_000.0)
    paper.set_mark_price("BTCUSDT", "spot", 60000.0)

    profile = StrategyProfile(name="oms-kill", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()

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
    with pytest.raises(KillSwitchActive):
        await oms.dispatch(
            orders=[order],
            state=_state(),
            strategy_name="test_strategy",
            profile_id=profile.id,
            profile_version=1,
            profile_hash="abc",
        )


@pytest.mark.asyncio
async def test_dispatch_unconfigured_venue_raises(db_session: AsyncSession) -> None:
    from app.oms.exceptions import UnconfiguredVenueError

    params = ProfileParams(profile={})
    profile = StrategyProfile(name="oms-uc", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()

    oms = OMS(
        exchanges={},  # no adapters
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
    with pytest.raises(UnconfiguredVenueError):
        await oms.dispatch(
            orders=[order],
            state=_state(),
            strategy_name="test_strategy",
            profile_id=profile.id,
            profile_version=1,
            profile_hash="abc",
        )


@pytest.mark.asyncio
async def test_dispatch_hedge_drift_raises(db_session: AsyncSession) -> None:
    from app.backtest.state import Position
    from app.oms.exceptions import HedgeDriftHalt

    params = ProfileParams(profile={})
    paper = PaperExchange(venue="binance", params=params, initial_cash=10_000.0)
    paper.set_mark_price("BTCUSDT", "spot", 60000.0)

    profile = StrategyProfile(name="oms-hedge", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()

    # Synthetic state: spot 0.1, perp -0.11 → 10% drift, > 5% threshold
    drifted_state = MarketState(
        snapshot=MarketSnapshot(ts_ms=1714521600000, bars={}),
        positions=(
            Position(venue="binance", symbol="BTCUSDT", product="spot",
                     qty_base=0.1, avg_entry_px=60000.0),
            Position(venue="binance", symbol="BTCUSDT", product="perp",
                     qty_base=-0.11, avg_entry_px=60000.0),
        ),
        cash_quote=10_000.0,
    )

    oms = OMS(
        exchanges={"binance": paper},
        audit_service=DecisionAuditService(db_session),
        params=params,
        kill_switch=KillSwitch(params=params),
        reconciler=PositionReconciler(params=params),
        ledger=MultiVenueCashLedger(),
    )

    # Empty orders list — no exchange interaction; just trigger reconciliation
    with pytest.raises(HedgeDriftHalt):
        await oms.dispatch(
            orders=[],
            state=drifted_state,
            strategy_name="test_strategy",
            profile_id=profile.id,
            profile_version=1,
            profile_hash="abc",
        )
