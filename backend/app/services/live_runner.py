"""LiveRunner — continuous tick loop: state -> strategy -> OMS -> audit.

Phase 8 default-safe: ``live.enabled=False`` + ``live.dry_run_mode=True``.
The loop calls ``run_one_tick()`` once per ``live.tick_interval_s``. Stop via
``runner.stop()`` (graceful — finishes current tick).

Every numeric / interval / toggle this module reads lives in the profile
registry (Constraint #1). The same ``ProfileParams`` instance drives both
the backtester and this runner (Constraint #2).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from app.backtest.state import MarketSnapshot, MarketState
from app.exchanges.base import Exchange
from app.oms.exceptions import KillSwitchActive
from app.oms.service import OMS
from app.profile.params import ProfileParams
from app.risk.drawdown_brake import DrawdownBrake
from app.risk.exceptions import DrawdownBrakeHalt
from app.risk.vol_estimator import RollingVolEstimator
from app.services.alerter import Alerter
from app.services.decision_audit import DecisionAuditService
from app.services.live_state_fetcher import LiveStateFetcher
from app.services.runner_state import RunnerStateService

logger = logging.getLogger(__name__)

_MS_PER_SECOND = 1000
# Rolling window length for the realized-vol estimator. Lives here (not in the
# profile registry) because it's a fixed unit-of-measure constant — 30 bars of
# 1m closes is the minimum the strategy needs to produce a usable annualised
# stdev. Tunable per-strategy parameters still live in the profile.
_VOL_ESTIMATOR_WINDOW_BARS = 30
_SPOT_PRODUCT = "spot"

_STATUS_DISABLED = "disabled"
_STATUS_NO_ORDERS = "no_orders"
_STATUS_KILL_SWITCH = "kill_switch"
_STATUS_OK = "ok"
_STATUS_HALTED_DRAWDOWN_BRAKE = "halted_drawdown_brake"
_STATUS_HALTED_HEDGE_DRIFT = "halted_hedge_drift"
_STATUS_HALTED_BOOK_DRIFT = "halted_book_drift"

_SEVERITY_CRITICAL = "critical"
_SEVERITY_WARNING = "warning"

_EVENT_DRAWDOWN_BRAKE = "DrawdownBrakeHalt"
_EVENT_KILL_SWITCH = "KillSwitchActive"
_EVENT_HEDGE_DRIFT = "HedgeDriftHalt"
_EVENT_BOOK_DRIFT = "ReconciliationDriftHalt"
_EVENT_HEARTBEAT = "heartbeat"


class LiveRunner:
    """Drive one trading cycle per tick: fetch state, evaluate, dispatch, audit.

    The runner is intentionally thin — it owns the loop cadence + drawdown
    brake + heartbeat snapshots, and delegates everything else to the
    Phase 5-7 components. ``run_one_tick`` is split out for tests; ``run``
    is the production forever-loop.
    """

    def __init__(
        self,
        *,
        exchanges: dict[str, Exchange],
        strategy: Any,
        oms: OMS,
        audit_service: DecisionAuditService,
        params: ProfileParams,
        drawdown_brake: DrawdownBrake,
        alerter: Alerter,
        venue: str,
        symbols: list[str],
        profile_id: uuid.UUID,
        profile_version: int,
        profile_hash: str,
        runner_state: RunnerStateService | None = None,
    ) -> None:
        self._exchanges = exchanges
        self._strategy = strategy
        self._oms = oms
        self._audit = audit_service
        self._params = params
        self._brake = drawdown_brake
        self._alerter = alerter
        self._fetcher = LiveStateFetcher(exchanges=exchanges, venue=venue)
        self._venue = venue
        self._symbols = symbols
        self._profile_id = profile_id
        self._profile_version = profile_version
        self._profile_hash = profile_hash
        self._runner_state = runner_state
        self._stopped = False
        self._last_snapshot_ts_ms: int = 0
        # Peak persisted to runner_state; tracked so we only write when it
        # strictly ratchets up (one row per new high-water mark).
        self._persisted_peak: float = self._brake.peak
        # HP7: per-runner rolling-vol estimator. Strategies read the resulting
        # ``realized_vols`` map off ``MarketSnapshot``; the estimator itself
        # stays internal so callers can't accidentally seed it from outside.
        self._vol_estimator = RollingVolEstimator(window_bars=_VOL_ESTIMATOR_WINDOW_BARS)

    def stop(self) -> None:
        """Signal the loop to exit after the current tick finishes."""
        self._stopped = True

    async def hydrate(self) -> None:
        """Restore persisted runner state into in-memory components.

        Currently restores ``peak_equity`` into the drawdown brake. No-op when
        no ``RunnerStateService`` was wired in or no row exists yet (cold
        start). Must be called before the first ``run_one_tick()``.
        """
        if self._runner_state is None:
            return
        stored = await self._runner_state.get("peak_equity")
        if stored is None:
            return
        peak = float(stored["value"])
        self._brake.set_peak(peak)
        self._persisted_peak = peak

    async def run_one_tick(self) -> dict[str, Any]:
        """Execute one iteration of the live loop.

        Returns:
            Dict describing the tick outcome (status, equity, peak). Tests
            assert on this dict; the production ``run`` loop ignores it.
        """
        if not bool(self._params.get("live.enabled")):
            return {"status": _STATUS_DISABLED}
        state = await self._fetcher.fetch_market_state(symbols=self._symbols)
        state = self._hydrate_realized_vols(state)
        orders = self._strategy.evaluate(state, self._params)
        result_status = _STATUS_NO_ORDERS
        if orders:
            try:
                dispatch = await self._oms.dispatch(
                    orders=orders,
                    state=state,
                    strategy_name=self._strategy.name,
                    profile_id=self._profile_id,
                    profile_version=self._profile_version,
                    profile_hash=self._profile_hash,
                )
                result_status = dispatch.reconciliation_status
            except KillSwitchActive:
                result_status = _STATUS_KILL_SWITCH
                await self._alerter.send(
                    severity=_SEVERITY_CRITICAL,
                    event=_EVENT_KILL_SWITCH,
                    details={},
                )
        # OMS-reported reconciliation drift halts → warning alert.
        if result_status == _STATUS_HALTED_HEDGE_DRIFT:
            await self._alerter.send(
                severity=_SEVERITY_WARNING,
                event=_EVENT_HEDGE_DRIFT,
                details={"strategy": self._strategy.name},
            )
        elif result_status == _STATUS_HALTED_BOOK_DRIFT:
            await self._alerter.send(
                severity=_SEVERITY_WARNING,
                event=_EVENT_BOOK_DRIFT,
                details={"strategy": self._strategy.name},
            )
        # Drawdown brake — equity = cash + mark-to-market(positions).
        equity = state.cash_quote + self._mark_to_market(state)
        try:
            self._brake.check(equity)
        except DrawdownBrakeHalt as e:
            await self._maybe_persist_peak()
            logger.warning("drawdown brake triggered: %s", e)
            await self._log_snapshot(state, equity, _STATUS_HALTED_DRAWDOWN_BRAKE, str(e))
            await self._alerter.send(
                severity=_SEVERITY_CRITICAL,
                event=_EVENT_DRAWDOWN_BRAKE,
                details={"equity": equity, "peak": self._brake.peak},
            )
            raise
        # Persist new high-water marks so a restart resumes from the same peak.
        await self._maybe_persist_peak()
        # Periodic heartbeat snapshot to the audit log.
        snapshot_logged = await self._maybe_log_snapshot(state, equity)
        if snapshot_logged and bool(self._params.get("alerts.send_heartbeats")):
            await self._alerter.send(
                severity=str(self._params.get("alerts.heartbeat_severity")),
                event=_EVENT_HEARTBEAT,
                details={"equity": equity, "peak": self._brake.peak},
            )
        return {
            "status": result_status,
            "equity": equity,
            "peak": self._brake.peak,
        }

    async def run(self) -> None:
        """Run the tick loop until ``stop()`` is called or the brake halts."""
        interval = float(self._params.get("live.tick_interval_s"))
        while not self._stopped:
            try:
                await self.run_one_tick()
            except DrawdownBrakeHalt:
                self._stopped = True
                break
            except Exception:  # noqa: BLE001
                logger.exception("tick failed; continuing")
            await asyncio.sleep(interval)

    def _hydrate_realized_vols(self, state: MarketState) -> MarketState:
        """Record spot bar closes into the estimator and inject realized vols.

        Returns a new ``MarketState`` whose snapshot carries the latest
        ``realized_vols`` map keyed by ``(venue, symbol)``. Perp bars are
        skipped — vol is measured on the spot leg to stay consistent with
        the backtest pipeline (which uses spot history from Parquet).

        Symbols whose estimator window is still too short to compute a
        sample variance yield 0.0; strategies fall back to a placeholder
        in that case (see ``RollingVolEstimator.annualised_vol``).
        """
        seen: set[tuple[str, str]] = set()
        for (venue, symbol, product), bar in state.snapshot.bars.items():
            if product != _SPOT_PRODUCT:
                continue
            self._vol_estimator.record(venue=venue, symbol=symbol, close_px=bar.close)
            seen.add((venue, symbol))
        realized_vols: dict[tuple[str, str], float] = {
            (venue, symbol): self._vol_estimator.annualised_vol(venue=venue, symbol=symbol)
            for (venue, symbol) in seen
        }
        new_snapshot = MarketSnapshot(
            ts_ms=state.snapshot.ts_ms,
            bars=state.snapshot.bars,
            funding_rates=state.snapshot.funding_rates,
            realized_vols=realized_vols,
        )
        return MarketState(
            snapshot=new_snapshot,
            positions=state.positions,
            cash_quote=state.cash_quote,
        )

    def _mark_to_market(self, state: MarketState) -> float:
        total = 0.0
        for pos in state.positions:
            bar = state.snapshot.bars.get((pos.venue, pos.symbol, pos.product))
            if bar is not None:
                total += pos.qty_base * bar.close
        return total

    async def _maybe_persist_peak(self) -> None:
        """Write a new high-water mark to runner_state if the brake's peak rose.

        No-op if no ``RunnerStateService`` is wired in, or if the brake's
        ``peak`` has not strictly increased since the last persisted value.
        """
        if self._runner_state is None:
            return
        current_peak = self._brake.peak
        if current_peak <= self._persisted_peak:
            return
        await self._runner_state.set(
            "peak_equity",
            {"value": current_peak, "ts_ms": int(time.time() * _MS_PER_SECOND)},
        )
        self._persisted_peak = current_peak

    async def _maybe_log_snapshot(self, state: MarketState, equity: float) -> bool:
        """Log a heartbeat snapshot if the interval has elapsed.

        Returns:
            True if a snapshot was written this tick, False otherwise.
            Callers use this to decide whether to fire a heartbeat alert.
        """
        interval_ms = int(float(self._params.get("live.snapshot_interval_s")) * _MS_PER_SECOND)
        now_ms = int(time.time() * _MS_PER_SECOND)
        if now_ms - self._last_snapshot_ts_ms < interval_ms:
            return False
        await self._log_snapshot(state, equity, _STATUS_OK, None)
        self._last_snapshot_ts_ms = now_ms
        return True

    async def _log_snapshot(
        self,
        state: MarketState,
        equity: float,
        status: str,
        reason: str | None,
    ) -> None:
        await self._audit.log_snapshot(
            ts=datetime.now(UTC),
            strategy_name=self._strategy.name,
            profile_id=self._profile_id,
            profile_version=self._profile_version,
            profile_hash=self._profile_hash,
            input_state={
                "cash": state.cash_quote,
                "equity": equity,
                "peak": self._brake.peak,
                "status": status,
                "reason": reason,
            },
        )
