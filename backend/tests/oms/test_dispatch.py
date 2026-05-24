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
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="market",
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
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="market",
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
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="market",
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
            Position(
                venue="binance",
                symbol="BTCUSDT",
                product="spot",
                qty_base=0.1,
                avg_entry_px=60000.0,
            ),
            Position(
                venue="binance",
                symbol="BTCUSDT",
                product="perp",
                qty_base=-0.11,
                avg_entry_px=60000.0,
            ),
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


@pytest.mark.asyncio
async def test_partial_fill_requeues_remainder(db_session: AsyncSession) -> None:
    """When adapter returns partially_filled, OMS retries the remainder."""
    from app.exchanges.types import Balance, OrderReceipt, OrderStatus

    class _PartialThenFullExchange:
        name = "binance"

        def __init__(self) -> None:
            self._calls = 0

        async def fetch_balance(self, quote_currency):  # type: ignore[no-untyped-def]
            return Balance(
                venue="binance",
                quote_currency=quote_currency,
                free=10_000.0,
                locked=0.0,
            )

        async def fetch_positions(self):  # type: ignore[no-untyped-def]
            return ()

        async def fetch_funding_rate(self, symbol):  # type: ignore[no-untyped-def]
            return None

        async def fetch_mark_price(self, symbol, product):  # type: ignore[no-untyped-def]
            return 60_000.0

        async def place_order(self, order):  # type: ignore[no-untyped-def]
            return OrderReceipt(
                order_id=f"id-{self._calls}",
                venue="binance",
                symbol=order.symbol,
                submitted_ts_ms=1,
            )

        async def fetch_order(self, order_id):  # type: ignore[no-untyped-def]
            self._calls += 1
            if self._calls == 1:
                return OrderStatus(
                    order_id=order_id,
                    status="partially_filled",
                    fill_px=60_000.0,
                    filled_qty_base=0.05,
                    fee_quote=0.5,
                    raw={},
                )
            return OrderStatus(
                order_id=order_id,
                status="filled",
                fill_px=60_000.0,
                filled_qty_base=0.05,
                fee_quote=0.5,
                raw={},
            )

        async def cancel_order(self, order_id):  # type: ignore[no-untyped-def]
            return

    params = ProfileParams(profile={})
    ex = _PartialThenFullExchange()
    profile = StrategyProfile(name="partial-test", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()

    oms = OMS(
        exchanges={"binance": ex},  # type: ignore[dict-item]
        audit_service=DecisionAuditService(db_session),
        params=params,
        kill_switch=KillSwitch(params=params),
        reconciler=PositionReconciler(params=params),
        ledger=MultiVenueCashLedger(),
    )
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="market",
    )
    result = await oms.dispatch(
        orders=[order],
        state=_state(),
        strategy_name="test",
        profile_id=profile.id,
        profile_version=1,
        profile_hash="abc",
    )
    # 2 fills: first partial (0.05), then completion (0.05)
    assert len(result.fills) >= 2
    total_qty = sum(f.order.qty_base for f in result.fills)
    assert abs(total_qty - 0.1) < 1e-6


@pytest.mark.asyncio
async def test_hedge_auto_rebalance_when_enabled(db_session: AsyncSession) -> None:
    """When oms.hedge_auto_rebalance_enabled=True, drift triggers a closing order."""
    from app.backtest.state import Position

    params = ProfileParams(profile={"oms": {"hedge_auto_rebalance_enabled": True}})
    paper = PaperExchange(venue="binance", params=params, initial_cash=10_000.0)
    paper.set_mark_price("BTCUSDT", "spot", 60_000.0)
    paper.set_mark_price("BTCUSDT", "perp", 60_000.0)
    profile = StrategyProfile(name="rebal-test", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()

    # spot 0.1, perp -0.11 → 10% drift > 5% threshold
    drifted_state = MarketState(
        snapshot=MarketSnapshot(ts_ms=1714521600000, bars={}),
        positions=(
            Position(
                venue="binance",
                symbol="BTCUSDT",
                product="spot",
                qty_base=0.1,
                avg_entry_px=60_000.0,
            ),
            Position(
                venue="binance",
                symbol="BTCUSDT",
                product="perp",
                qty_base=-0.11,
                avg_entry_px=60_000.0,
            ),
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
    # Should NOT raise; should rebalance instead
    result = await oms.dispatch(
        orders=[],
        state=drifted_state,
        strategy_name="test",
        profile_id=profile.id,
        profile_version=1,
        profile_hash="abc",
    )
    assert result.reconciliation_status == "auto_rebalance"
