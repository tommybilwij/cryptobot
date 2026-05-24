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
from typing import Any, Literal

from app.backtest.orders import Fill, Order
from app.backtest.state import MarketState, Position
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
from app.services import correlation
from app.services.decision_audit import DecisionAuditService
from app.services.metrics_collector import collector as _metrics

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
_STATUS_AUTO_REBALANCE = "auto_rebalance"


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
        # Correlation ID — tags every log line + audit row in this dispatch's
        # async scope (contextvar propagates through `await`).
        correlation.set_dispatch_id(correlation.new_id())
        start_ms = time.time() * _MS_PER_SECOND
        ts = datetime.now(UTC)
        input_state = _serialize_state(state)
        input_state["dispatch_id"] = correlation.current()
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
            _metrics.record_dispatch(
                latency_ms=time.time() * _MS_PER_SECOND - start_ms,
                status=_STATUS_KILL_SWITCH,
            )
            _metrics.record_halt("KillSwitchActive")
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
                _metrics.record_dispatch(
                    latency_ms=time.time() * _MS_PER_SECOND - start_ms,
                    status=_STATUS_UNCONFIGURED_VENUE,
                )
                raise UnconfiguredVenueError(
                    f"{order.venue} not in configured exchanges; audit_entry_id={entry.id}"
                )

        # 3. Place orders sequentially and poll for terminal status.
        #    Partial fills auto-retry the remainder up to
        #    `oms.max_partial_fill_retries`; see `_place_with_partial_retry`.
        fills: list[Fill] = []
        try:
            for order in orders:
                ex = self._exchanges[order.venue]
                fills.extend(await self._place_with_partial_retry(ex, order))
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
            # Attribute the auth failure to the venue we were placing against
            # — `orders` is validated non-empty in step 2 by this point.
            _metrics.record_venue_error(orders[0].venue)
            _metrics.record_dispatch(
                latency_ms=time.time() * _MS_PER_SECOND - start_ms,
                status=_STATUS_AUTH_FAILED,
            )
            raise OMSError(f"auth failed during dispatch; audit_entry_id={entry.id}") from e

        # 4. Reconcile. Runs unconditionally — empty-orders dispatch still
        #    needs hedge-consistency to fire on pre-existing book drift.
        #    Book-vs-exchange only runs when we actually touched a venue (no
        #    orders → no exchange snapshot to compare against).
        reconciliation_status, reason, rebalance_fills = await self._reconcile(
            orders=orders, state=state
        )
        fills.extend(rebalance_fills)

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

        _metrics.record_dispatch(
            latency_ms=time.time() * _MS_PER_SECOND - start_ms,
            status=reconciliation_status,
        )

        if reconciliation_status == _STATUS_HALTED_HEDGE_DRIFT:
            assert reason is not None
            _metrics.record_halt("HedgeDriftHalt")
            raise HedgeDriftHalt(reason)
        if reconciliation_status == _STATUS_HALTED_BOOK_DRIFT:
            assert reason is not None
            _metrics.record_halt("ReconciliationDriftHalt")
            raise ReconciliationDriftHalt(reason)

        return DispatchResult(
            fills=fills,
            audit_entry_id=entry.id,
            reconciliation_status=reconciliation_status,
            reason=reason,
        )

    async def _reconcile(
        self, *, orders: list[Order], state: MarketState
    ) -> tuple[str, str | None, list[Fill]]:
        """Run book-vs-exchange + hedge-consistency checks.

        Returns ``(reconciliation_status, reason, rebalance_fills)``.
        Hedge drift with ``oms.hedge_auto_rebalance_enabled=True`` produces
        ``auto_rebalance`` status + the closing-leg fills; otherwise sets the
        halted status and the caller raises after the audit row lands.
        """
        rebalance_fills: list[Fill] = []
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
            # Opt-in: when `oms.hedge_auto_rebalance_enabled=True`, the OMS
            # closes the over-sized leg's excess instead of halting. Default
            # stays False — halting is the safe path.
            if bool(self._params.get("oms.hedge_auto_rebalance_enabled")):
                rebalance_fills = await self._auto_rebalance_hedge(state)
                return _STATUS_AUTO_REBALANCE, f"auto-rebalanced: {e}", rebalance_fills
            return _STATUS_HALTED_HEDGE_DRIFT, str(e), rebalance_fills
        except ReconciliationDriftHalt as e:
            return _STATUS_HALTED_BOOK_DRIFT, str(e), rebalance_fills
        return _STATUS_OK, None, rebalance_fills

    async def _place_with_partial_retry(
        self, exchange: Exchange, order: Order
    ) -> list[Fill]:
        """Place ``order``; re-queue any unfilled remainder up to N retries.

        Returns the list of fills (one per successful partial / full fill).
        Stops on:
          - full fill,
          - remainder below ``oms.partial_fill_min_remainder_qty``,
          - ``oms.max_partial_fill_retries`` exhausted,
          - cancelled / rejected / timed-out status.
        """
        fills: list[Fill] = []
        remaining_qty = order.qty_base
        max_retries = int(self._params.get("oms.max_partial_fill_retries"))
        min_remainder = float(self._params.get("oms.partial_fill_min_remainder_qty"))
        retries = 0
        while remaining_qty >= min_remainder and retries <= max_retries:
            retry_order = Order(
                venue=order.venue,
                symbol=order.symbol,
                product=order.product,
                side=order.side,
                qty_base=remaining_qty,
                order_type=order.order_type,
                limit_px=order.limit_px,
            )
            receipt = await exchange.place_order(retry_order)
            status = await self._poll_until_terminal(exchange, receipt.order_id)
            if status.status in _FILLED_STATUSES and status.fill_px is not None:
                # Record the Fill with the *actual* filled qty (which may be
                # less than the placed order on partials), so summing fills
                # across retries reconciles back to the original request.
                filled_leg = Order(
                    venue=retry_order.venue,
                    symbol=retry_order.symbol,
                    product=retry_order.product,
                    side=retry_order.side,
                    qty_base=status.filled_qty_base,
                    order_type=retry_order.order_type,
                    limit_px=retry_order.limit_px,
                )
                fills.append(
                    Fill(
                        ts_ms=int(time.time() * _MS_PER_SECOND),
                        order=filled_leg,
                        fill_px=status.fill_px,
                        fee_quote=status.fee_quote,
                    )
                )
                _metrics.record_fill(partial=(status.status == "partially_filled"))
                remaining_qty -= status.filled_qty_base
                if status.status == "filled" or remaining_qty < min_remainder:
                    break
            else:
                # rejected / cancelled / timed-out — stop retrying
                break
            retries += 1
        return fills

    async def _auto_rebalance_hedge(self, state: MarketState) -> list[Fill]:
        """Emit a closing order for the over-sized leg of each spot/perp pair.

        Walks every (venue, symbol) that has both legs; for any imbalance
        emits a market order on the over-sized leg in the direction that
        reduces its magnitude. Uses ``_place_with_partial_retry`` so the
        rebalance order itself benefits from partial-fill aggregation.
        """
        by_symbol: dict[tuple[str, str], dict[str, Position]] = {}
        for p in state.positions:
            key = (p.venue, p.symbol)
            by_symbol.setdefault(key, {})[p.product] = p

        fills: list[Fill] = []
        for (venue, symbol), legs in by_symbol.items():
            if "spot" not in legs or "perp" not in legs:
                continue
            spot_qty = abs(legs["spot"].qty_base)
            perp_qty = abs(legs["perp"].qty_base)
            if spot_qty == perp_qty:
                continue
            # Close the over-sized leg's excess. Side reduces magnitude:
            # long spot (qty > 0) → sell to reduce; short perp (qty < 0) → buy to reduce.
            if spot_qty > perp_qty:
                excess = spot_qty - perp_qty
                side: Literal["buy", "sell"] = "sell" if legs["spot"].qty_base > 0 else "buy"
                rebal_order = Order(
                    venue=venue,
                    symbol=symbol,
                    product="spot",
                    side=side,
                    qty_base=excess,
                    order_type="market",
                )
            else:
                excess = perp_qty - spot_qty
                side = "buy" if legs["perp"].qty_base < 0 else "sell"
                rebal_order = Order(
                    venue=venue,
                    symbol=symbol,
                    product="perp",
                    side=side,
                    qty_base=excess,
                    order_type="market",
                )
            ex = self._exchanges.get(venue)
            if ex is None:
                continue
            rebal_fills = await self._place_with_partial_retry(ex, rebal_order)
            fills.extend(rebal_fills)
        return fills

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
