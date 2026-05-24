# Cryptobot — Phase 8 Dry-Run + Live Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`.

**Goal:** Ship the live runner loop with default-safe `dry_run_mode=True` + `live.enabled=False` toggles. Drawdown brake halts at 5% drop. No real money risk until Phase 9 flips the flags.

**Architecture:** New `LiveRunner` service ties LiveStateFetcher + FundingArbStrategy + OMS into a continuous tick loop. New `risk/drawdown_brake.py`. New worker job `WORKER_JOB=live_trade`. New API endpoints `GET /api/v1/live/status` + `POST /api/v1/live/stop`. No DB changes — reuses Phase 5 DecisionAuditEntry for hourly snapshots.

**Spec:** `docs/superpowers/specs/2026-05-24-cryptobot-dryrun-design.md`.

**DoD:** ~223 tests pass. Gates clean. Runner runs against PaperExchange single-tick. Drawdown brake halts at threshold. Worker job + docker-compose service + just recipe wired. Safe-by-default config.

---

### Task 1: Profile registry — live + drawdown brake keys

Modify `backend/app/profile/defaults.py` + `backend/tests/test_profile_registry.py`.

Add NUMERIC:
```python
"live.tick_interval_s": 60.0,
"live.snapshot_interval_s": 3600.0,
"live.cold_start_grace_s": 300.0,
"risk.drawdown_brake.peak_equity": 0.0,
```

Add BOOL:
```python
"live.enabled": False,
"live.dry_run_mode": True,
```

Add STRING:
```python
"live.venue": "binance",
```

Append tests asserting all 7 keys present with correct defaults + types.

Commit: `feat: profile registry keys for live runner + drawdown brake`

---

### Task 2: Drawdown brake

Files: `backend/app/risk/__init__.py` (empty), `backend/app/risk/exceptions.py`, `backend/app/risk/drawdown_brake.py`, `backend/tests/risk/__init__.py` (empty), `backend/tests/risk/test_drawdown_brake.py`.

`exceptions.py`:
```python
"""Risk-class exception hierarchy."""

from __future__ import annotations


class RiskError(RuntimeError):
    """Base for halt-class risk errors."""


class DrawdownBrakeHalt(RiskError):
    """Equity dropped > trigger_pct from peak; halt trading."""
```

`drawdown_brake.py`:
```python
"""Drawdown brake — tracks rolling peak equity, halts on excessive drawdown.

Phase 8 ships binary halt at ``risk.drawdown_brake.trigger_pct`` (default 5%).
Graduated multipliers (Phase 10+) read ``risk.drawdown_brake.full_pct`` and
``min_mult`` to scale position sizes between trigger and full halt.
"""

from __future__ import annotations

from app.profile.params import ProfileParams
from app.risk.exceptions import DrawdownBrakeHalt


class DrawdownBrake:
    def __init__(self, *, params: ProfileParams) -> None:
        self._params = params
        self._peak: float = float(params.get("risk.drawdown_brake.peak_equity"))

    @property
    def peak(self) -> float:
        return self._peak

    def check(self, equity: float) -> None:
        """Update peak if new high, raise DrawdownBrakeHalt if drop > trigger."""
        if equity > self._peak:
            self._peak = equity
            return
        if self._peak <= 0.0:
            return  # cold start, no halt possible
        drawdown_pct = (equity - self._peak) / self._peak
        trigger = -abs(float(self._params.get("risk.drawdown_brake.trigger_pct")))
        if drawdown_pct < trigger:
            raise DrawdownBrakeHalt(
                f"equity {equity:.2f} below peak {self._peak:.2f} by "
                f"{drawdown_pct:.4f}, trigger={trigger:.4f}"
            )
```

Tests in `test_drawdown_brake.py`:
- `test_seeds_peak_on_first_tick` — empty brake, check(10_000) → peak = 10_000
- `test_updates_peak_on_new_high` — peak=10_000, check(11_000) → peak=11_000
- `test_halts_at_trigger_threshold` — peak=10_000, check(9_499) (5.01% drop) → raises
- `test_holds_above_trigger` — peak=10_000, check(9_700) (3% drop) → no raise
- `test_zero_peak_no_halt` — peak=0, check(any) → no raise (cold start)

Commit: `feat: DrawdownBrake — halt on equity drop > trigger_pct`

---

### Task 3: LiveRunner service

Files: `backend/app/services/live_runner.py`, `backend/tests/services/test_live_runner.py`.

```python
"""LiveRunner — continuous tick loop: state → strategy → OMS → audit.

Phase 8 default-safe: ``live.enabled=False`` + ``live.dry_run_mode=True``.
The loop calls ``run_one_tick()`` once per ``live.tick_interval_s``. Stop via
``runner.stop()`` (graceful — finishes current tick).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from app.backtest.state import MarketState
from app.exchanges.base import Exchange
from app.oms.exceptions import KillSwitchActive
from app.oms.service import OMS
from app.profile.params import ProfileParams
from app.risk.drawdown_brake import DrawdownBrake
from app.risk.exceptions import DrawdownBrakeHalt
from app.services.decision_audit import DecisionAuditService
from app.services.live_state_fetcher import LiveStateFetcher

logger = logging.getLogger(__name__)


class LiveRunner:
    def __init__(
        self,
        *,
        exchanges: dict[str, Exchange],
        strategy: Any,
        oms: OMS,
        audit_service: DecisionAuditService,
        params: ProfileParams,
        drawdown_brake: DrawdownBrake,
        venue: str,
        symbols: list[str],
        profile_id: uuid.UUID,
        profile_version: int,
        profile_hash: str,
    ) -> None:
        self._exchanges = exchanges
        self._strategy = strategy
        self._oms = oms
        self._audit = audit_service
        self._params = params
        self._brake = drawdown_brake
        self._fetcher = LiveStateFetcher(exchanges=exchanges, venue=venue)
        self._venue = venue
        self._symbols = symbols
        self._profile_id = profile_id
        self._profile_version = profile_version
        self._profile_hash = profile_hash
        self._stopped = False
        self._last_snapshot_ts_ms: int = 0

    def stop(self) -> None:
        self._stopped = True

    async def run_one_tick(self) -> dict[str, Any]:
        """Execute one iteration. Returns dict with tick outcome for tests."""
        if not bool(self._params.get("live.enabled")):
            return {"status": "disabled"}
        state = await self._fetcher.fetch_market_state(symbols=self._symbols)
        orders = self._strategy.evaluate(state, self._params)
        result_status = "no_orders"
        if orders:
            try:
                dispatch = await self._oms.dispatch(
                    orders=orders, state=state,
                    strategy_name=self._strategy.name,
                    profile_id=self._profile_id,
                    profile_version=self._profile_version,
                    profile_hash=self._profile_hash,
                )
                result_status = dispatch.reconciliation_status
            except KillSwitchActive:
                result_status = "kill_switch"
        # Drawdown brake — based on cash + position mark-to-market
        equity = state.cash_quote + self._mark_to_market(state)
        try:
            self._brake.check(equity)
        except DrawdownBrakeHalt as e:
            logger.warning("drawdown brake triggered: %s", e)
            await self._log_snapshot(state, equity, "halted_drawdown_brake", str(e))
            raise
        # Hourly snapshot
        await self._maybe_log_snapshot(state, equity)
        return {"status": result_status, "equity": equity, "peak": self._brake.peak}

    async def run(self) -> None:
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

    def _mark_to_market(self, state: MarketState) -> float:
        total = 0.0
        for pos in state.positions:
            bar = state.snapshot.bars.get((pos.venue, pos.symbol, pos.product))
            if bar is not None:
                total += pos.qty_base * bar.close
        return total

    async def _maybe_log_snapshot(self, state: MarketState, equity: float) -> None:
        interval_ms = int(float(self._params.get("live.snapshot_interval_s")) * 1000)
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_snapshot_ts_ms < interval_ms:
            return
        await self._log_snapshot(state, equity, "ok", None)
        self._last_snapshot_ts_ms = now_ms

    async def _log_snapshot(
        self, state: MarketState, equity: float, status: str, reason: str | None
    ) -> None:
        # Use DecisionAuditService.log_decision with decision_type="snapshot"-like role
        # — we use log_snapshot which forces decision_type="snapshot".
        await self._audit.log_snapshot(
            ts=datetime.now(UTC),
            strategy_name=self._strategy.name,
            profile_id=self._profile_id,
            profile_version=self._profile_version,
            profile_hash=self._profile_hash,
            input_state={
                "cash": state.cash_quote, "equity": equity,
                "peak": self._brake.peak, "status": status,
                "reason": reason,
            },
        )
```

Tests cover:
- `test_skips_when_disabled` — `live.enabled=False` profile → returns `{"status": "disabled"}`, no fetcher call
- `test_dispatches_when_strategy_emits_orders` — mock strategy returns 2 orders → OMS.dispatch invoked
- `test_skips_dispatch_when_no_orders` — strategy returns [] → status "no_orders"
- `test_halts_on_drawdown_brake` — peak=10_000 (via profile), state equity 9_000 → raises
- `test_logs_snapshot_after_interval` — set last_snapshot_ts_ms = old → snapshot logged

Use PaperExchange + a stub strategy + real OMS + DecisionAuditService via db_session fixture.

Commit: `feat: LiveRunner service ties state + strategy + OMS into a tick loop`

---

### Task 4: Worker job + docker-compose service

Files: `backend/app/worker/jobs/live_trade.py`, modify `backend/app/worker/main.py`, modify `docker-compose.yml`, modify `justfile`, modify `backend/tests/test_worker_jobs.py`.

`live_trade.py`:
```python
"""Worker job — drives the LiveRunner loop.

Loads active profile, builds dependencies, runs the loop until stopped.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os

from sqlalchemy import select

from app.deps import get_session_factory
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


def _hash(d: dict) -> str:
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def run() -> None:
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
        # Phase 8: always PaperExchange in dry-run; real adapter wiring is Phase 9
        exchanges = {
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
        await runner.run()
```

Modify `worker/main.py` `_JOBS`:
```python
"live_trade": live_trade.run,
```

Modify `docker-compose.yml` — add new service:
```yaml
  worker-live-trade:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: cryptobot-worker-live-trade
    restart: "unless-stopped"
    command: uv run python -m app.worker.main
    environment:
      WORKER_JOB: live_trade
      DATABASE_URL: postgresql+asyncpg://cryptobot:${POSTGRES_PASSWORD:-devpass}@postgres:5432/cryptobot
      DATABASE_URL_SYNC: postgresql+psycopg://cryptobot:${POSTGRES_PASSWORD:-devpass}@postgres:5432/cryptobot
    volumes:
      - ./data:/app/data
    depends_on:
      postgres:
        condition: service_healthy
    profiles: ["live"]
```

Modify `justfile`:
```just

# Start the live runner loop (uses WORKER_JOB=live_trade); dry-run by default
live-trade:
    cd backend && WORKER_JOB=live_trade uv run python -m app.worker.main
```

Append to `test_worker_jobs.py`:
```python
@pytest.mark.asyncio
async def test_live_trade_dispatches() -> None:
    from app.worker.main import _resolve_job

    job = _resolve_job("live_trade")
    assert callable(job)
```

Commit: `feat: WORKER_JOB=live_trade + docker-compose worker-live-trade + just recipe`

---

### Task 5: GET /api/v1/live/status + POST /api/v1/live/stop

Files: `backend/app/api/live.py`, `backend/app/schemas/live.py`, modify `backend/app/main.py`, `backend/tests/api/test_live.py`.

`schemas/live.py`:
```python
"""Pydantic v2 schemas for /api/v1/live endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LiveStatusResponse(BaseModel):
    enabled: bool
    dry_run_mode: bool
    venue: str
    last_tick_ts: datetime | None
    last_reconciliation_status: str | None
    last_equity_quote: float | None
    peak_equity_quote: float
    drawdown_pct: float | None


class LiveStopResponse(BaseModel):
    active_profile_id: str
    live_enabled: bool
    new_version: int
```

`api/live.py`:
```python
"""HTTP API for live runner state."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.models.decision_audit import DecisionAuditEntry
from app.models.strategy_profile import StrategyProfile
from app.profile.params import ProfileParams
from app.schemas.live import LiveStatusResponse, LiveStopResponse

router = APIRouter(prefix="/api/v1/live", tags=["live"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _active_profile(db: AsyncSession) -> StrategyProfile | None:
    result = await db.execute(
        select(StrategyProfile).where(StrategyProfile.is_active.is_(True))
    )
    return result.scalar_one_or_none()


@router.get("/status", response_model=LiveStatusResponse)
async def get_status(db: DbSession) -> LiveStatusResponse:
    profile = await _active_profile(db)
    config = profile.config if profile else {}
    params = ProfileParams(profile=config)
    last_q = await db.execute(
        select(DecisionAuditEntry).order_by(DecisionAuditEntry.ts.desc()).limit(1)
    )
    last_entry = last_q.scalar_one_or_none()
    peak = float(params.get("risk.drawdown_brake.peak_equity"))
    last_equity: float | None = None
    if last_entry is not None and isinstance(last_entry.input_state, dict):
        eq = last_entry.input_state.get("equity")
        if isinstance(eq, (int, float)):
            last_equity = float(eq)
    drawdown_pct: float | None = None
    if last_equity is not None and peak > 0.0:
        drawdown_pct = (last_equity - peak) / peak
    return LiveStatusResponse(
        enabled=bool(params.get("live.enabled")),
        dry_run_mode=bool(params.get("live.dry_run_mode")),
        venue=str(params.get("live.venue")),
        last_tick_ts=last_entry.ts if last_entry else None,
        last_reconciliation_status=(
            last_entry.reconciliation_status if last_entry else None
        ),
        last_equity_quote=last_equity,
        peak_equity_quote=peak,
        drawdown_pct=drawdown_pct,
    )


@router.post("/stop", response_model=LiveStopResponse)
async def stop(db: DbSession) -> LiveStopResponse:
    profile = await _active_profile(db)
    if profile is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "no active profile to stop"
        )
    new_config = dict(profile.config) if profile.config else {}
    live_section = dict(new_config.get("live", {}))
    live_section["enabled"] = False
    new_config["live"] = live_section
    profile.config = new_config
    profile.version = profile.version + 1
    await db.flush()
    await db.commit()
    return LiveStopResponse(
        active_profile_id=str(profile.id),
        live_enabled=False,
        new_version=profile.version,
    )
```

Modify `main.py` to register `live` router.

Tests in `test_live.py`:
- `test_status_returns_default_state` — no active profile → response with sane defaults
- `test_status_reflects_active_profile_flags` — profile with `live.enabled=True` → response shows True
- `test_stop_flips_enabled_to_false` — POST /stop on active profile → flips flag + bumps version

Commit: `feat: GET /api/v1/live/status + POST /api/v1/live/stop`

---

### Task 6: README + final sweep

Append to README after "Testnet integration (Phase 7)":

```markdown

## Dry-run + Live runner (Phase 8)

The live runner loop ties Strategy A → OMS → exchange adapters into a continuous
cycle. **Default-safe**: `live.enabled=False` AND `live.dry_run_mode=True` — even
if you fire the worker, nothing trades real money.

### Toggles (in active profile)

| Key | Default | Meaning |
|---|---|---|
| `live.enabled` | `False` | Master gate. `False` → loop skips every tick. |
| `live.dry_run_mode` | `True` | `True` → PaperExchange in-memory fills. `False` → real adapter (Phase 9). |
| `live.tick_interval_s` | `60.0` | Seconds between loop iterations. |
| `live.snapshot_interval_s` | `3600.0` | Hourly heartbeat snapshot to DecisionAuditEntry. |
| `live.venue` | `"binance"` | Which venue adapter to use. |
| `risk.drawdown_brake.trigger_pct` | `0.05` | Halt loop if equity drops 5% from peak. |

### Run locally

```bash
just live-trade
```

### Run via Docker

```bash
docker compose --profile live up worker-live-trade
```

### Status + stop

```bash
curl http://localhost:8000/api/v1/live/status
curl -X POST http://localhost:8000/api/v1/live/stop
```

### Deferred

- **Real money** → Phase 9 (after dry-run validates over days/weeks)
- **Kelly + vol-target sizing** → Phase 10+
- **WebSocket fills** → Phase 11+
```

Full sweep. Commit: `docs: README Phase 8 dry-run + live runner section`

---

### Task 7: PR via /pr-summary

MINOR bump v0.7.0 → v0.8.0. Parent agent runs the pipeline.

---

## Plan self-review

- Spec coverage: registry (1), brake (2), runner (3), worker+compose (4), API (5), docs (6), PR (7).
- Type consistency: reuses Phase 4-7 types throughout.
- Constraint #1: no literals in `app/services/live_runner.py` or `app/risk/`. AST lint will need extension in a Phase 9+ pass (not Task 6 — Phase 8 source-tree is small).
- Constraint #4: `audit_service.log_snapshot` carries `profile_id`/`profile_version`/`profile_hash` — pipeline unchanged.
- Safe-by-default: `live.enabled=False` + `live.dry_run_mode=True` baked into registry defaults.
