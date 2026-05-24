"""OMS service — dispatch strategy orders to live exchanges with reconciliation.

Flow per ``dispatch()`` call:

1. Kill switch check (before any exchange contact). If the active profile has
   ``oms.kill_switch_active=True``, an audit entry is logged with status
   ``kill_switch`` and ``KillSwitchActive`` is raised.
2. Validate every order's venue maps to a configured ``Exchange``. Otherwise
   log + raise ``UnconfiguredVenueError`` — fail fast before placing any
   partial set.
3. Place each order sequentially. For each receipt poll
   ``Exchange.fetch_order`` until a terminal status (``filled``,
   ``partially_filled``, ``cancelled``, ``rejected``) is reached, or
   ``oms.max_fill_wait_s`` elapses (then cancel + return last status).
4. Run the reconciler unconditionally — book vs exchange drift then hedge
   consistency. Empty-orders dispatch is the supported shape for "check
   reconciliation only" (used by the dedicated drift halt test).
5. Log one audit entry capturing input state, orders, fills, and the final
   reconciliation status. Raise the matching halt class if the reconciler
   signalled drift.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.backtest.orders import Fill, Order
from app.backtest.state import MarketState
from app.exchanges.base import Exchange
from app.exchanges.errors import AuthFailed
from app.exchanges.types import ExchangePosition, OrderStatus
from app.oms.exceptions import (
    HedgeDriftHalt,
    KillSwitchActive,
    OMSError,
    ReconciliationDriftHalt,
    UnconfiguredVenueError,
)
from app.oms.kill_switch import KillSwitch
from app.oms.ledger import MultiVenueCashLedger
from app.oms.reconciler import PositionReconciler
from app.profile.params import ProfileParams
from app.services.decision_audit import DecisionAuditService

_MS_PER_SECOND = 1000
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"filled", "partially_filled", "cancelled", "rejected"}
)
_FILLED_STATUSES: frozenset[str] = frozenset({"filled", "partially_filled"})

_STATUS_OK = "ok"
_STATUS_KILL_SWITCH = "kill_switch"
_STATUS_UNCONFIGURED_VENUE = "unconfigured_venue"
_STATUS_AUTH_FAILED = "auth_failed"
_STATUS_HALTED_HEDGE_DRIFT = "halted_hedge_drift"
_STATUS_HALTED_BOOK_DRIFT = "halted_book_drift"


@dataclass
class DispatchResult:
    """Outcome of a single ``OMS.dispatch`` call."""

    fills: list[Fill]
    audit_entry_id: uuid.UUID
    reconciliation_status: str
    reason: str | None = None


class OMS:
    """Order Management System — bridges strategy ``Order``s to live exchanges."""

    def __init__(
        self,
        *,
        exchanges: dict[str, Exchange],
        audit_service: DecisionAuditService,
        params: ProfileParams,
        kill_switch: KillSwitch,
        reconciler: PositionReconciler,
        ledger: MultiVenueCashLedger,
    ) -> None:
        self._exchanges = exchanges
        self._audit = audit_service
        self._params = params
        self._kill_switch = kill_switch
        self._reconciler = reconciler
        self._ledger = ledger

    async def dispatch(
        self,
        *,
        orders: list[Order],
        state: MarketState,
        strategy_name: str,
        profile_id: uuid.UUID,
        profile_version: int,
        profile_hash: str,
    ) -> DispatchResult:
        ts = datetime.now(UTC)
        input_state = _serialize_state(state)
        order_dicts = [_serialize_order(o) for o in orders]

        # 1. Kill switch check (before any exchange contact).
        if self._kill_switch.is_active():
            entry = await self._audit.log_decision(
                ts=ts,
                strategy_name=strategy_name,
                profile_id=profile_id,
                profile_version=profile_version,
                profile_hash=profile_hash,
                input_state=input_state,
                orders=order_dicts,
                fills=[],
                reconciliation_status=_STATUS_KILL_SWITCH,
                reason="kill switch active",
            )
            raise KillSwitchActive(f"kill switch active; audit_entry_id={entry.id}")

        # 2. Validate each order's venue is configured.
        for order in orders:
            if order.venue not in self._exchanges:
                entry = await self._audit.log_decision(
                    ts=ts,
                    strategy_name=strategy_name,
                    profile_id=profile_id,
                    profile_version=profile_version,
                    profile_hash=profile_hash,
                    input_state=input_state,
                    orders=order_dicts,
                    fills=[],
                    reconciliation_status=_STATUS_UNCONFIGURED_VENUE,
                    reason=f"venue {order.venue} not configured",
                )
                raise UnconfiguredVenueError(
                    f"{order.venue} not in configured exchanges; audit_entry_id={entry.id}"
                )

        # 3. Place orders sequentially and poll for terminal status.
        fills: list[Fill] = []
        try:
            for order in orders:
                ex = self._exchanges[order.venue]
                receipt = await ex.place_order(order)
                status = await self._poll_until_terminal(ex, receipt.order_id)
                if status.status in _FILLED_STATUSES and status.fill_px is not None:
                    fills.append(
                        Fill(
                            ts_ms=int(time.time() * _MS_PER_SECOND),
                            order=order,
                            fill_px=status.fill_px,
                            fee_quote=status.fee_quote,
                        )
                    )
        except AuthFailed as e:
            entry = await self._audit.log_decision(
                ts=ts,
                strategy_name=strategy_name,
                profile_id=profile_id,
                profile_version=profile_version,
                profile_hash=profile_hash,
                input_state=input_state,
                orders=order_dicts,
                fills=[_serialize_fill(f) for f in fills],
                reconciliation_status=_STATUS_AUTH_FAILED,
                reason=str(e),
            )
            raise OMSError(f"auth failed during dispatch; audit_entry_id={entry.id}") from e

        # 4. Reconcile. Runs unconditionally — empty-orders dispatch still
        #    needs hedge-consistency to fire on pre-existing book drift.
        #    Book-vs-exchange only runs when we actually touched a venue (no
        #    orders → no exchange snapshot to compare against).
        reconciliation_status = _STATUS_OK
        reason: str | None = None
        try:
            touched_venues: set[str] = {o.venue for o in orders}
            if touched_venues:
                ex_positions: list[ExchangePosition] = []
                for venue in touched_venues:
                    ex_positions.extend(await self._exchanges[venue].fetch_positions())
                self._reconciler.check_book_vs_exchange(
                    book_positions=state.positions,
                    exchange_positions=tuple(ex_positions),
                )
            self._reconciler.check_hedge_consistency(positions=state.positions)
        except HedgeDriftHalt as e:
            reconciliation_status = _STATUS_HALTED_HEDGE_DRIFT
            reason = str(e)
        except ReconciliationDriftHalt as e:
            reconciliation_status = _STATUS_HALTED_BOOK_DRIFT
            reason = str(e)

        # 5. Log a single audit entry summarising the dispatch.
        entry = await self._audit.log_decision(
            ts=ts,
            strategy_name=strategy_name,
            profile_id=profile_id,
            profile_version=profile_version,
            profile_hash=profile_hash,
            input_state=input_state,
            orders=order_dicts,
            fills=[_serialize_fill(f) for f in fills],
            reconciliation_status=reconciliation_status,
            reason=reason,
        )

        if reconciliation_status == _STATUS_HALTED_HEDGE_DRIFT:
            assert reason is not None
            raise HedgeDriftHalt(reason)
        if reconciliation_status == _STATUS_HALTED_BOOK_DRIFT:
            assert reason is not None
            raise ReconciliationDriftHalt(reason)

        return DispatchResult(
            fills=fills,
            audit_entry_id=entry.id,
            reconciliation_status=reconciliation_status,
            reason=reason,
        )

    async def _poll_until_terminal(self, ex: Exchange, order_id: str) -> OrderStatus:
        """Poll ``fetch_order`` until terminal status or timeout.

        On timeout, best-effort ``cancel_order`` and return the last status.
        """
        poll_interval = float(self._params.get("oms.fill_poll_interval_s"))
        max_wait = float(self._params.get("oms.max_fill_wait_s"))
        deadline = time.monotonic() + max_wait
        status = await ex.fetch_order(order_id)
        while status.status not in _TERMINAL_STATUSES:
            if time.monotonic() >= deadline:
                await ex.cancel_order(order_id)
                return status
            await asyncio.sleep(poll_interval)
            status = await ex.fetch_order(order_id)
        return status


def _serialize_order(o: Order) -> dict[str, Any]:
    return {
        "venue": o.venue,
        "symbol": o.symbol,
        "product": o.product,
        "side": o.side,
        "qty_base": o.qty_base,
        "order_type": o.order_type,
        "limit_px": o.limit_px,
    }


def _serialize_fill(f: Fill) -> dict[str, Any]:
    return {
        "ts_ms": f.ts_ms,
        "fill_px": f.fill_px,
        "fee_quote": f.fee_quote,
        "order": _serialize_order(f.order),
    }


def _serialize_state(state: MarketState) -> dict[str, Any]:
    return {
        "ts_ms": state.snapshot.ts_ms,
        "cash_quote": state.cash_quote,
        "positions": [
            {
                "venue": p.venue,
                "symbol": p.symbol,
                "product": p.product,
                "qty_base": p.qty_base,
                "avg_entry_px": p.avg_entry_px,
            }
            for p in state.positions
        ],
    }
