# Cryptobot — Phase 4 Backtester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land an async, profile-driven backtest engine that walks historical Parquet bars via `DuckDBQuery`, executes a pure `Strategy.evaluate(state, params) → list[Order]` function, applies a constant-bps fill + fee + funding model, and persists results to Postgres (`backtest_runs`) + Parquet (`data/backtest_runs/{id}.parquet`).

**Architecture:** Event-driven engine in `backend/app/backtest/`. HTTP `POST /api/v1/backtests` inserts a pending row + locks `profile_hash` (audit Constraint #4); worker job `WORKER_JOB=run_backtest BACKTEST_ID=<uuid>` picks it up, runs the engine, persists summary stats + equity curve, marks complete. `GET /api/v1/backtests/{id}` polls. Same `ProfileParams` accessor pattern as Phase 1+2 — no hardcoded values in `backtest/engine.py`, `fills.py`, `funding.py`, `metrics.py`, or strategy files (Constraint #1, enforced by AST lint).

**Tech Stack:** Polars 1.x, DuckDB 1.x, SQLAlchemy 2.x async + asyncpg, FastAPI, Pydantic v2, Alembic, pytest + pytest-asyncio. All existing.

**Scope:** Phase 4 only. Spec: `docs/superpowers/specs/2026-05-24-cryptobot-backtester-design.md`. Blocks Phase 5 (exchange adapters), Phase 6 (Strategy A funding arb), Phase 14+ (factor portfolio backtests, IC discipline).

**Definition of done (gate to Phase 5):**
- ~89 tests total pass (64 existing + ~25 new); mypy `--strict` clean; ruff + AST lint clean
- `POST /api/v1/backtests` + `GET /api/v1/backtests/{id}` work end-to-end via manual smoke against `BuyAndHoldStrategy` over BTCUSDT Parquet data from Phase 3
- `FundingArbSkeleton` over synthetic funding fixture: total funding payments collected match `Σ(notional × funding_rate)` exactly
- Alembic migration `0003_create_backtest_runs` applies + reverses cleanly
- `BacktestRun.profile_hash` set on every row (audit Constraint #4)
- `docker compose --profile jobs config --quiet` exits 0 with the new `worker-run-backtest` service
- No numeric literals in `backtest/engine.py`, `fills.py`, `funding.py`, `metrics.py`, or any strategy file (AST lint extended + enforced)

---

## Phase 4.1: Registry + dataclass foundations

### Task 1: Profile registry additions for execution + backtest defaults

**Files:**
- Modify: `backend/app/profile/defaults.py`
- Modify: `backend/tests/test_profile_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_profile_registry.py`:

```python
def test_execution_slippage_keys_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    for venue in ("binance", "bybit", "hyperliquid"):
        key = f"execution.slippage_bps.{venue}"
        assert key in PROFILE_SCOPED_DEFAULTS, f"missing {key}"
        assert isinstance(PROFILE_SCOPED_DEFAULTS[key], float)


def test_execution_fee_keys_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    expected = [
        "execution.fee_bps.binance.spot",
        "execution.fee_bps.binance.perp",
        "execution.fee_bps.bybit.perp",
        "execution.fee_bps.hyperliquid.perp",
    ]
    for key in expected:
        assert key in PROFILE_SCOPED_DEFAULTS, f"missing {key}"
        assert isinstance(PROFILE_SCOPED_DEFAULTS[key], float)


def test_backtest_keys_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    assert PROFILE_SCOPED_DEFAULTS["backtest.initial_cash_quote_usdc"] == 10_000.0
    assert PROFILE_SCOPED_DEFAULTS["backtest.bar_interval_s"] == 60
    assert PROFILE_SCOPED_DEFAULTS["metrics.minutes_per_year"] == 525_600
```

- [ ] **Step 2: Verify FAILS**

```bash
cd backend && uv run pytest tests/test_profile_registry.py::test_execution_slippage_keys_present -v
```
Expected: KeyError / AssertionError on missing keys.

- [ ] **Step 3: Add the keys to `PROFILE_SCOPED_DEFAULTS`**

In `backend/app/profile/defaults.py`, add to the existing `PROFILE_SCOPED_DEFAULTS` dict:

```python
# --- execution (fees + slippage; used by backtest fill sim + live OMS) ---
"execution.slippage_bps.binance": 5.0,
"execution.slippage_bps.bybit": 5.0,
"execution.slippage_bps.hyperliquid": 8.0,
"execution.fee_bps.binance.spot": 10.0,
"execution.fee_bps.binance.perp": 4.0,
"execution.fee_bps.bybit.perp": 5.5,
"execution.fee_bps.hyperliquid.perp": 3.5,

# --- backtest harness ---
"backtest.initial_cash_quote_usdc": 10_000.0,
"backtest.bar_interval_s": 60,
"metrics.minutes_per_year": 525_600,
```

- [ ] **Step 4: Tests pass**

```bash
cd backend && uv run pytest tests/test_profile_registry.py -v
```
Expected: all profile registry tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/profile/defaults.py backend/tests/test_profile_registry.py
git commit -m "feat: profile registry keys for execution + backtest defaults"
```

---

### Task 2: backtest package + state dataclasses

**Files:**
- Create: `backend/app/backtest/__init__.py`
- Create: `backend/app/backtest/state.py`
- Create: `backend/tests/backtest/__init__.py`
- Create: `backend/tests/backtest/test_state.py`

- [ ] **Step 1: Failing test**

`backend/tests/backtest/__init__.py`: empty file.

`backend/tests/backtest/test_state.py`:
```python
"""Tests for backtest state dataclasses."""

from __future__ import annotations

import pytest

from app.backtest.state import Bar, MarketSnapshot, MarketState, Position


def test_bar_is_frozen() -> None:
    bar = Bar(
        ts_ms=1714521600000,
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        open=60000.0,
        high=60015.0,
        low=59995.0,
        close=60010.0,
        volume=10.5,
    )
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        bar.close = 99.0  # type: ignore[misc]


def test_market_snapshot_lookup_by_key() -> None:
    bar = Bar(
        ts_ms=1714521600000,
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        open=60000.0,
        high=60015.0,
        low=59995.0,
        close=60010.0,
        volume=10.5,
    )
    snap = MarketSnapshot(ts_ms=1714521600000, bars={("binance", "BTCUSDT", "spot"): bar})
    assert snap.bars[("binance", "BTCUSDT", "spot")].close == 60010.0


def test_position_signed_qty() -> None:
    long = Position(venue="binance", symbol="BTCUSDT", product="spot", qty_base=0.5, avg_entry_px=60000.0)
    short = Position(venue="binance", symbol="BTCUSDT", product="perp", qty_base=-0.5, avg_entry_px=60010.0)
    assert long.qty_base > 0
    assert short.qty_base < 0


def test_market_state_positions_are_tuple() -> None:
    state = MarketState(
        snapshot=MarketSnapshot(ts_ms=0, bars={}),
        positions=(),
        cash_quote=10000.0,
    )
    assert isinstance(state.positions, tuple)
```

- [ ] **Step 2: Verify FAILS** (ImportError on `app.backtest.state`).

- [ ] **Step 3: Implement**

`backend/app/backtest/__init__.py`:
```python
"""Backtest engine — same-profile-as-live event-driven simulator.

See ``docs/superpowers/specs/2026-05-24-cryptobot-backtester-design.md`` for
architecture and the audit-trail contract (Constraint #4).
"""
```

`backend/app/backtest/state.py`:
```python
"""Frozen dataclasses describing market state at a single tick.

Strategies see ``MarketState`` and return ``list[Order]``. The engine owns
position bookkeeping; strategies are pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Product = Literal["spot", "perp"]


@dataclass(frozen=True)
class Bar:
    ts_ms: int
    venue: str
    symbol: str
    product: Product
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class MarketSnapshot:
    ts_ms: int
    bars: dict[tuple[str, str, Product], Bar]


@dataclass(frozen=True)
class Position:
    venue: str
    symbol: str
    product: Product
    qty_base: float
    avg_entry_px: float


@dataclass(frozen=True)
class MarketState:
    snapshot: MarketSnapshot
    positions: tuple[Position, ...]
    cash_quote: float
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_state.py -v
git add backend/app/backtest/__init__.py backend/app/backtest/state.py backend/tests/backtest/__init__.py backend/tests/backtest/test_state.py
git commit -m "feat: backtest state dataclasses (Bar, MarketSnapshot, Position, MarketState)"
```

---

### Task 3: Order + Fill dataclasses

**Files:**
- Create: `backend/app/backtest/orders.py`
- Create: `backend/tests/backtest/test_orders.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for Order + Fill dataclasses."""

from __future__ import annotations

import pytest

from app.backtest.orders import Fill, Order


def test_order_is_frozen() -> None:
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="market",
    )
    with pytest.raises(Exception):
        order.qty_base = 99.0  # type: ignore[misc]


def test_order_limit_carries_limit_px() -> None:
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="limit",
        limit_px=59000.0,
    )
    assert order.limit_px == 59000.0


def test_market_order_has_no_limit_px() -> None:
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="sell",
        qty_base=0.1,
        order_type="market",
    )
    assert order.limit_px is None


def test_fill_records_fee_and_price() -> None:
    order = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        side="buy",
        qty_base=0.1,
        order_type="market",
    )
    fill = Fill(ts_ms=1714521600000, order=order, fill_px=60030.0, fee_quote=6.0)
    assert fill.fill_px == 60030.0
    assert fill.fee_quote == 6.0
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/backtest/orders.py`:
```python
"""Order + Fill dataclasses — strategies return ``list[Order]``; engine produces ``Fill`` objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.backtest.state import Product

OrderType = Literal["market", "limit"]
Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Order:
    venue: str
    symbol: str
    product: Product
    side: Side
    qty_base: float
    order_type: OrderType
    limit_px: float | None = None


@dataclass(frozen=True)
class Fill:
    ts_ms: int
    order: Order
    fill_px: float
    fee_quote: float
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_orders.py -v
git add backend/app/backtest/orders.py backend/tests/backtest/test_orders.py
git commit -m "feat: backtest Order + Fill dataclasses"
```

---

## Phase 4.2: ORM + migration

### Task 4: BacktestRun ORM

**Files:**
- Create: `backend/app/models/backtest_run.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Implement**

`backend/app/models/backtest_run.py`:
```python
"""BacktestRun ORM — persists backtest jobs with audit-locked profile snapshot."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BacktestRun(Base):
    """A backtest job — async lifecycle (pending → running → complete | failed)."""

    __tablename__ = "backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_profiles.id"),
        nullable=False,
    )
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(80), nullable=False)
    venue: Mapped[str] = mapped_column(String(40), nullable=False)
    symbols: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    num_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    equity_curve_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

Update `backend/app/models/__init__.py` to register the new model:
```python
"""ORM models. Import models here so Alembic autogenerate picks them up."""

from app.models.backtest_run import BacktestRun
from app.models.base import Base
from app.models.data_health_event import DataHealthEvent
from app.models.strategy_profile import StrategyProfile
from app.models.symbol_manifest_snapshot import SymbolManifestSnapshot

__all__ = [
    "Base",
    "BacktestRun",
    "DataHealthEvent",
    "StrategyProfile",
    "SymbolManifestSnapshot",
]
```

- [ ] **Step 2: Gates green**

```bash
just typecheck && just lint && just test
```
Expected: existing 64 tests still pass; mypy +1 source file.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/backtest_run.py backend/app/models/__init__.py
git commit -m "feat: BacktestRun ORM"
```

---

### Task 5: Alembic migration 0003 — backtest_runs

**Files:**
- Create: `backend/alembic/versions/0003_create_backtest_runs.py`

- [ ] **Step 1: Autogenerate**

Ensure Postgres is running (`just up`), then:

```bash
cd backend && uv run alembic revision --autogenerate -m "create_backtest_runs"
```

This creates `backend/alembic/versions/<rand>_create_backtest_runs.py`.

- [ ] **Step 2: Rename + normalize header**

Rename to `0003_create_backtest_runs.py` and set:
```python
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None
```

Verify `upgrade()` creates `backtest_runs` table with columns matching the ORM (id UUID PK, profile_id UUID FK → strategy_profiles, profile_version int, profile_hash str(64), strategy_name str(80), venue str(40), symbols ARRAY(str(40)), start_ts/end_ts/started_at/completed_at/created_at DateTime(tz), status str(20), total_return/sharpe/max_drawdown Float, num_trades int, equity_curve_path str(255), error_message Text). Verify `downgrade()` drops the table.

If autogen has spurious diffs (e.g. the orphan `ix_strategy_profiles_active` index from Phase 3 still appearing), strip them out — this migration's scope is `backtest_runs` only.

- [ ] **Step 3: Apply + verify**

```bash
just mig-up
docker compose exec postgres psql -U cryptobot -d cryptobot -c "\d backtest_runs"
```
Expected: table shown with all columns + FK constraint to strategy_profiles.

- [ ] **Step 4: Round-trip**

```bash
cd backend && uv run alembic downgrade 0002 && uv run alembic upgrade head
```
Expected: both succeed.

- [ ] **Step 5: Gates + commit**

```bash
just typecheck && just lint && just test
git add backend/alembic/versions/0003_create_backtest_runs.py
git commit -m "feat: alembic migration adding backtest_runs table"
```

---

## Phase 4.3: Engine internals (TDD)

### Task 6: PositionBook

**Files:**
- Create: `backend/app/backtest/positions.py`
- Create: `backend/tests/backtest/test_positions.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for PositionBook — tracks open positions, applies fills, marks to market."""

from __future__ import annotations

from app.backtest.orders import Fill, Order
from app.backtest.positions import PositionBook
from app.backtest.state import Bar, MarketSnapshot


def _market_buy(qty: float, venue: str = "binance", symbol: str = "BTCUSDT") -> Order:
    return Order(
        venue=venue, symbol=symbol, product="spot", side="buy",
        qty_base=qty, order_type="market",
    )


def _market_sell(qty: float, venue: str = "binance", symbol: str = "BTCUSDT") -> Order:
    return Order(
        venue=venue, symbol=symbol, product="spot", side="sell",
        qty_base=qty, order_type="market",
    )


def test_open_long_from_empty() -> None:
    book = PositionBook()
    book.apply([Fill(ts_ms=0, order=_market_buy(0.5), fill_px=60000.0, fee_quote=3.0)])
    positions = book.snapshot()
    assert len(positions) == 1
    assert positions[0].qty_base == 0.5
    assert positions[0].avg_entry_px == 60000.0


def test_add_to_long_updates_avg_entry() -> None:
    book = PositionBook()
    book.apply([Fill(ts_ms=0, order=_market_buy(0.5), fill_px=60000.0, fee_quote=0.0)])
    book.apply([Fill(ts_ms=0, order=_market_buy(0.5), fill_px=62000.0, fee_quote=0.0)])
    positions = book.snapshot()
    assert positions[0].qty_base == 1.0
    assert positions[0].avg_entry_px == 61000.0


def test_partial_close_reduces_qty_keeps_avg_entry() -> None:
    book = PositionBook()
    book.apply([Fill(ts_ms=0, order=_market_buy(1.0), fill_px=60000.0, fee_quote=0.0)])
    book.apply([Fill(ts_ms=0, order=_market_sell(0.4), fill_px=61000.0, fee_quote=0.0)])
    positions = book.snapshot()
    assert positions[0].qty_base == 0.6
    assert positions[0].avg_entry_px == 60000.0


def test_full_close_removes_position() -> None:
    book = PositionBook()
    book.apply([Fill(ts_ms=0, order=_market_buy(1.0), fill_px=60000.0, fee_quote=0.0)])
    book.apply([Fill(ts_ms=0, order=_market_sell(1.0), fill_px=61000.0, fee_quote=0.0)])
    assert book.snapshot() == ()


def test_mark_to_market_uses_close() -> None:
    book = PositionBook()
    book.apply([Fill(ts_ms=0, order=_market_buy(1.0), fill_px=60000.0, fee_quote=0.0)])
    bar = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="spot",
        open=61000.0, high=61500.0, low=60500.0, close=61200.0, volume=10.0,
    )
    snap = MarketSnapshot(ts_ms=1, bars={("binance", "BTCUSDT", "spot"): bar})
    assert book.mark_to_market(snap) == 61200.0  # 1.0 BTC * 61200


def test_short_perp_mark_to_market_is_negative_notional() -> None:
    book = PositionBook()
    sell = Order(
        venue="binance", symbol="BTCUSDT", product="perp", side="sell",
        qty_base=0.5, order_type="market",
    )
    book.apply([Fill(ts_ms=0, order=sell, fill_px=60000.0, fee_quote=0.0)])
    bar = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="perp",
        open=61000.0, high=61000.0, low=61000.0, close=61000.0, volume=1.0,
    )
    snap = MarketSnapshot(ts_ms=1, bars={("binance", "BTCUSDT", "perp"): bar})
    # short 0.5 perp marked at 61000 → -30500 (mark value of liability)
    assert book.mark_to_market(snap) == -30500.0
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/backtest/positions.py`:
```python
"""PositionBook — applies fills to maintain open positions; marks them to market."""

from __future__ import annotations

from app.backtest.orders import Fill
from app.backtest.state import Position, Product

_PositionKey = tuple[str, str, Product]


class PositionBook:
    """Mutable book of open positions keyed by (venue, symbol, product)."""

    def __init__(self) -> None:
        self._positions: dict[_PositionKey, Position] = {}

    def apply(self, fills: list[Fill]) -> None:
        for fill in fills:
            order = fill.order
            key: _PositionKey = (order.venue, order.symbol, order.product)
            delta = fill.qty_base_signed
            existing = self._positions.get(key)
            if existing is None:
                self._positions[key] = Position(
                    venue=order.venue,
                    symbol=order.symbol,
                    product=order.product,
                    qty_base=delta,
                    avg_entry_px=fill.fill_px,
                )
                continue
            new_qty = existing.qty_base + delta
            if new_qty == 0.0:
                del self._positions[key]
                continue
            same_sign = (existing.qty_base > 0) == (new_qty > 0) and (delta * existing.qty_base) > 0
            if same_sign:
                # adding to position → weighted average entry
                new_avg = (
                    (existing.avg_entry_px * abs(existing.qty_base))
                    + (fill.fill_px * abs(delta))
                ) / (abs(existing.qty_base) + abs(delta))
                self._positions[key] = Position(
                    venue=existing.venue,
                    symbol=existing.symbol,
                    product=existing.product,
                    qty_base=new_qty,
                    avg_entry_px=new_avg,
                )
            else:
                # partial close → keep avg_entry
                self._positions[key] = Position(
                    venue=existing.venue,
                    symbol=existing.symbol,
                    product=existing.product,
                    qty_base=new_qty,
                    avg_entry_px=existing.avg_entry_px,
                )

    def snapshot(self) -> tuple[Position, ...]:
        return tuple(self._positions.values())

    def mark_to_market(self, snapshot: "MarketSnapshot") -> float:  # noqa: F821
        total = 0.0
        for pos in self._positions.values():
            key: _PositionKey = (pos.venue, pos.symbol, pos.product)
            bar = snapshot.bars.get(key)
            if bar is None:
                continue
            total += pos.qty_base * bar.close
        return total
```

Also add `qty_base_signed` property on `Fill`. Modify `backend/app/backtest/orders.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.backtest.state import Product

OrderType = Literal["market", "limit"]
Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Order:
    venue: str
    symbol: str
    product: Product
    side: Side
    qty_base: float
    order_type: OrderType
    limit_px: float | None = None


@dataclass(frozen=True)
class Fill:
    ts_ms: int
    order: Order
    fill_px: float
    fee_quote: float

    @property
    def qty_base_signed(self) -> float:
        return self.order.qty_base if self.order.side == "buy" else -self.order.qty_base
```

Update `MarketSnapshot` forward reference in `positions.py`:
```python
from app.backtest.state import MarketSnapshot  # add to imports
```
and remove the string forward-ref `"MarketSnapshot"` annotation.

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_positions.py tests/backtest/test_orders.py -v
git add backend/app/backtest/positions.py backend/app/backtest/orders.py backend/tests/backtest/test_positions.py
git commit -m "feat: PositionBook with weighted-avg entry + mark-to-market"
```

---

### Task 7: FillSimulator

**Files:**
- Create: `backend/app/backtest/fills.py`
- Create: `backend/tests/backtest/test_fills.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for FillSimulator — constant-bps slippage + fees from profile."""

from __future__ import annotations

import pytest

from app.backtest.fills import FillSimulator, InsufficientCashError
from app.backtest.orders import Order
from app.backtest.state import Bar, MarketSnapshot
from app.profile.defaults import PROFILE_SCOPED_DEFAULTS
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(values=dict(PROFILE_SCOPED_DEFAULTS))


def _snap(close: float = 60000.0, venue: str = "binance", symbol: str = "BTCUSDT", product: str = "spot") -> MarketSnapshot:
    bar = Bar(
        ts_ms=1, venue=venue, symbol=symbol, product=product,
        open=close, high=close, low=close, close=close, volume=100.0,
    )
    return MarketSnapshot(ts_ms=1, bars={(venue, symbol, product): bar})


def test_market_buy_pays_up_with_slippage() -> None:
    sim = FillSimulator(params=_params())
    order = Order(venue="binance", symbol="BTCUSDT", product="spot", side="buy", qty_base=0.1, order_type="market")
    fills, cash_after = sim.fill([order], _snap(60000.0), cash=10_000.0)
    # 5 bps slippage → fill at 60030
    assert fills[0].fill_px == pytest.approx(60030.0)
    # Fee: 10 bps of notional = 10 / 10_000 * (0.1 * 60030) = 6.003
    assert fills[0].fee_quote == pytest.approx(6.003, rel=1e-4)


def test_market_sell_gets_discounted_by_slippage() -> None:
    sim = FillSimulator(params=_params())
    order = Order(venue="binance", symbol="BTCUSDT", product="spot", side="sell", qty_base=0.1, order_type="market")
    fills, _ = sim.fill([order], _snap(60000.0), cash=10_000.0)
    # 5 bps slippage on sell → 60000 * (1 - 0.0005) = 59970
    assert fills[0].fill_px == pytest.approx(59970.0)


def test_buy_with_insufficient_cash_raises() -> None:
    sim = FillSimulator(params=_params())
    order = Order(venue="binance", symbol="BTCUSDT", product="spot", side="buy", qty_base=10.0, order_type="market")
    with pytest.raises(InsufficientCashError):
        sim.fill([order], _snap(60000.0), cash=1000.0)


def test_limit_order_fills_if_touched_in_bar() -> None:
    sim = FillSimulator(params=_params())
    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot", side="buy",
        qty_base=0.1, order_type="limit", limit_px=59500.0,
    )
    bar = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="spot",
        open=60000.0, high=60100.0, low=59400.0, close=60050.0, volume=10.0,
    )
    snap = MarketSnapshot(ts_ms=1, bars={("binance", "BTCUSDT", "spot"): bar})
    fills, _ = sim.fill([order], snap, cash=10_000.0)
    assert fills[0].fill_px == 59500.0


def test_limit_order_dropped_if_not_touched() -> None:
    sim = FillSimulator(params=_params())
    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot", side="buy",
        qty_base=0.1, order_type="limit", limit_px=58000.0,
    )
    bar = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="spot",
        open=60000.0, high=60100.0, low=59400.0, close=60050.0, volume=10.0,
    )
    snap = MarketSnapshot(ts_ms=1, bars={("binance", "BTCUSDT", "spot"): bar})
    fills, _ = sim.fill([order], snap, cash=10_000.0)
    assert fills == []
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/backtest/fills.py`:
```python
"""FillSimulator — applies constant-bps slippage + venue/product fees from the profile."""

from __future__ import annotations

from app.backtest.orders import Fill, Order
from app.backtest.state import MarketSnapshot
from app.profile.params import ProfileParams

_BPS_DIVISOR = 10_000.0


class InsufficientCashError(RuntimeError):
    """Raised when a buy order would push cash below zero."""


class FillSimulator:
    def __init__(self, *, params: ProfileParams) -> None:
        self._params = params

    def fill(
        self,
        orders: list[Order],
        snapshot: MarketSnapshot,
        *,
        cash: float,
    ) -> tuple[list[Fill], float]:
        fills: list[Fill] = []
        cash_left = cash
        for order in orders:
            bar = snapshot.bars.get((order.venue, order.symbol, order.product))
            if bar is None:
                continue
            fill_px = self._compute_fill_px(order, bar.close, bar)
            if fill_px is None:
                continue
            slippage_bps = self._params.get(f"execution.slippage_bps.{order.venue}")
            fee_bps = self._params.get(
                f"execution.fee_bps.{order.venue}.{order.product}"
            )
            assert isinstance(slippage_bps, (int, float))
            assert isinstance(fee_bps, (int, float))
            notional = abs(order.qty_base) * fill_px
            fee = notional * (float(fee_bps) / _BPS_DIVISOR)
            if order.side == "buy":
                cost = notional + fee
                if cost > cash_left:
                    raise InsufficientCashError(
                        f"buy {order.symbol} cost {cost:.2f} > cash {cash_left:.2f}"
                    )
                cash_left -= cost
            else:
                cash_left += notional - fee
            fills.append(Fill(ts_ms=snapshot.ts_ms, order=order, fill_px=fill_px, fee_quote=fee))
        return fills, cash_left

    def _compute_fill_px(self, order: Order, close: float, bar) -> float | None:  # type: ignore[no-untyped-def]
        slippage_bps = self._params.get(f"execution.slippage_bps.{order.venue}")
        assert isinstance(slippage_bps, (int, float))
        slip = float(slippage_bps) / _BPS_DIVISOR
        if order.order_type == "market":
            if order.side == "buy":
                return close * (1.0 + slip)
            return close * (1.0 - slip)
        # limit
        if order.limit_px is None:
            return None
        if bar.low <= order.limit_px <= bar.high:
            return order.limit_px
        return None
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_fills.py -v
git add backend/app/backtest/fills.py backend/tests/backtest/test_fills.py
git commit -m "feat: FillSimulator with constant-bps slippage + fees from profile"
```

---

### Task 8: FundingLedger

**Files:**
- Create: `backend/app/backtest/funding.py`
- Create: `backend/tests/backtest/test_funding.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for FundingLedger — applies per-venue funding payments at venue cadence."""

from __future__ import annotations

import polars as pl

from app.backtest.funding import FundingLedger, FundingEvent
from app.backtest.state import Position


def _funding_df(events: list[tuple[int, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts_ms": [t for t, _ in events],
            "predicted": [r for _, r in events],
            "realized": [r for _, r in events],
        }
    )


def test_no_perp_position_no_op() -> None:
    ledger = FundingLedger()
    pos_long_spot = Position(
        venue="binance", symbol="BTCUSDT", product="spot",
        qty_base=0.5, avg_entry_px=60000.0,
    )
    events = ledger.events_for(
        positions=(pos_long_spot,),
        ts_ms=1714521600000,
        funding_data={},
        mark_pxs={},
    )
    assert events == []


def test_short_perp_collects_positive_funding() -> None:
    ledger = FundingLedger()
    short = Position(
        venue="binance", symbol="BTCUSDT", product="perp",
        qty_base=-0.5, avg_entry_px=60000.0,
    )
    df = _funding_df([(1714521600000, 0.0001)])  # 1 bps funding
    events = ledger.events_for(
        positions=(short,),
        ts_ms=1714521600000,
        funding_data={("binance", "BTCUSDT"): df},
        mark_pxs={("binance", "BTCUSDT", "perp"): 60000.0},
    )
    # short 0.5 BTC @ 60000 = -30000 notional; positive funding → short collects
    # payment = -sign(qty) * notional * rate = +1 * 30000 * 0.0001 = +3.0
    assert len(events) == 1
    assert events[0].payment_quote == 3.0


def test_long_perp_pays_positive_funding() -> None:
    ledger = FundingLedger()
    long = Position(
        venue="binance", symbol="BTCUSDT", product="perp",
        qty_base=0.5, avg_entry_px=60000.0,
    )
    df = _funding_df([(1714521600000, 0.0001)])
    events = ledger.events_for(
        positions=(long,),
        ts_ms=1714521600000,
        funding_data={("binance", "BTCUSDT"): df},
        mark_pxs={("binance", "BTCUSDT", "perp"): 60000.0},
    )
    assert events[0].payment_quote == -3.0


def test_no_event_when_ts_not_in_funding_data() -> None:
    ledger = FundingLedger()
    short = Position(
        venue="binance", symbol="BTCUSDT", product="perp",
        qty_base=-0.5, avg_entry_px=60000.0,
    )
    df = _funding_df([(1714521600000, 0.0001)])
    events = ledger.events_for(
        positions=(short,),
        ts_ms=1714521660000,  # one minute later, no funding event here
        funding_data={("binance", "BTCUSDT"): df},
        mark_pxs={("binance", "BTCUSDT", "perp"): 60000.0},
    )
    assert events == []
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/backtest/funding.py`:
```python
"""FundingLedger — applies perp funding payments at venue-defined cadence.

Convention: positive funding rate means longs pay shorts.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from app.backtest.state import Position


@dataclass(frozen=True)
class FundingEvent:
    ts_ms: int
    venue: str
    symbol: str
    position_qty: float
    funding_rate: float
    mark_px: float
    payment_quote: float


class FundingLedger:
    """Stateless: events_for(...) is called once per tick by the engine."""

    def events_for(
        self,
        *,
        positions: tuple[Position, ...],
        ts_ms: int,
        funding_data: dict[tuple[str, str], pl.DataFrame],
        mark_pxs: dict[tuple[str, str, str], float],
    ) -> list[FundingEvent]:
        events: list[FundingEvent] = []
        for pos in positions:
            if pos.product != "perp":
                continue
            if pos.qty_base == 0.0:
                continue
            df = funding_data.get((pos.venue, pos.symbol))
            if df is None:
                continue
            match = df.filter(pl.col("ts_ms") == ts_ms)
            if match.height == 0:
                continue
            rate = float(match["realized"][0])
            mark_px = mark_pxs.get((pos.venue, pos.symbol, "perp"))
            if mark_px is None:
                continue
            notional = abs(pos.qty_base) * mark_px
            sign = 1.0 if pos.qty_base > 0 else -1.0
            payment = -sign * notional * rate
            events.append(
                FundingEvent(
                    ts_ms=ts_ms,
                    venue=pos.venue,
                    symbol=pos.symbol,
                    position_qty=pos.qty_base,
                    funding_rate=rate,
                    mark_px=mark_px,
                    payment_quote=payment,
                )
            )
        return events
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_funding.py -v
git add backend/app/backtest/funding.py backend/tests/backtest/test_funding.py
git commit -m "feat: FundingLedger with per-venue funding payment at venue cadence"
```

---

### Task 9: Metrics

**Files:**
- Create: `backend/app/backtest/metrics.py`
- Create: `backend/tests/backtest/test_metrics.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for backtest metrics — Sharpe (24/7 annualised), max_dd, total_return."""

from __future__ import annotations

import math

import polars as pl

from app.backtest.metrics import compute_metrics
from app.profile.defaults import PROFILE_SCOPED_DEFAULTS
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(values=dict(PROFILE_SCOPED_DEFAULTS))


def test_total_return_simple() -> None:
    curve = pl.DataFrame({"ts_ms": [0, 60_000], "equity": [10_000.0, 11_000.0]})
    metrics = compute_metrics(curve, params=_params())
    assert metrics.total_return == 0.1


def test_max_drawdown_simple() -> None:
    # 10000 → 12000 (peak) → 9000 (trough) → 11000
    # dd = (9000 - 12000) / 12000 = -0.25
    curve = pl.DataFrame(
        {"ts_ms": [0, 60_000, 120_000, 180_000], "equity": [10_000.0, 12_000.0, 9_000.0, 11_000.0]}
    )
    metrics = compute_metrics(curve, params=_params())
    assert metrics.max_drawdown == -0.25


def test_sharpe_uses_minutes_per_year_from_registry() -> None:
    # Constant +0.01% per minute return → mean=0.0001, std=0, sharpe undefined.
    # Use a noisier curve.
    n = 1000
    equities = [10_000.0]
    for i in range(1, n):
        rate = 0.0001 if i % 2 == 0 else -0.00005  # alternating returns
        equities.append(equities[-1] * (1 + rate))
    curve = pl.DataFrame({"ts_ms": list(range(0, n * 60_000, 60_000)), "equity": equities})
    metrics = compute_metrics(curve, params=_params())
    # sharpe should be a finite number
    assert math.isfinite(metrics.sharpe)


def test_num_trades_counted_from_trade_log() -> None:
    curve = pl.DataFrame({"ts_ms": [0, 60_000], "equity": [10_000.0, 10_010.0]})
    metrics = compute_metrics(curve, params=_params(), num_trades=3)
    assert metrics.num_trades == 3
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/backtest/metrics.py`:
```python
"""Equity curve → summary metrics (total_return, sharpe, max_drawdown, num_trades)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import polars as pl

from app.profile.params import ProfileParams


@dataclass(frozen=True)
class BacktestMetrics:
    total_return: float
    sharpe: float
    max_drawdown: float
    num_trades: int


def compute_metrics(
    equity_curve: pl.DataFrame,
    *,
    params: ProfileParams,
    num_trades: int = 0,
) -> BacktestMetrics:
    if equity_curve.height < 2:
        return BacktestMetrics(
            total_return=0.0, sharpe=0.0, max_drawdown=0.0, num_trades=num_trades
        )

    equity = equity_curve["equity"].to_list()
    first = equity[0]
    last = equity[-1]
    total_return = (last - first) / first if first != 0.0 else 0.0

    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0.0:
            dd = (value - peak) / peak
            max_dd = min(max_dd, dd)

    returns: list[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        if prev != 0.0:
            returns.append((equity[i] - prev) / prev)

    minutes_per_year = params.get("metrics.minutes_per_year")
    bar_interval_s = params.get("backtest.bar_interval_s")
    assert isinstance(minutes_per_year, (int, float))
    assert isinstance(bar_interval_s, (int, float))
    # convert "minutes per year" to "bars per year" given the bar interval
    bars_per_year = float(minutes_per_year) * (60.0 / float(bar_interval_s))

    if len(returns) < 2:
        sharpe = 0.0
    else:
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(var)
        sharpe = (mean / std) * math.sqrt(bars_per_year) if std > 0.0 else 0.0

    return BacktestMetrics(
        total_return=total_return,
        sharpe=sharpe,
        max_drawdown=max_dd,
        num_trades=num_trades,
    )
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_metrics.py -v
git add backend/app/backtest/metrics.py backend/tests/backtest/test_metrics.py
git commit -m "feat: backtest metrics (Sharpe annualised 24/7, max_dd, total_return)"
```

---

### Task 10: Loader — Parquet → MarketSnapshot generator

**Files:**
- Create: `backend/app/backtest/loader.py`
- Create: `backend/tests/backtest/test_loader.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for backtest data loader — Parquet → MarketSnapshot generator."""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path

import polars as pl
import pytest

from app.backtest.loader import BacktestDataError, BacktestLoader
from app.market_data.parquet_store import ParquetStore


def _write_klines(store: ParquetStore, year: int, month: int) -> None:
    # Three consecutive 1m bars starting at 2024-01-01 00:00 UTC
    base = 1704067200000
    df = pl.DataFrame(
        {
            "ts_ms": [base, base + 60_000, base + 120_000],
            "open": [60000.0, 60100.0, 60200.0],
            "high": [60050.0, 60150.0, 60250.0],
            "low": [59950.0, 60050.0, 60150.0],
            "close": [60010.0, 60110.0, 60210.0],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=year, month=month)


def test_loader_iterates_snapshots(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
    _write_klines(store, 2024, 1)
    loader = BacktestLoader(parquet_root=tmp_path)
    start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 2, 0, tzinfo=UTC)
    snaps = list(
        loader.iter_snapshots(
            venue="binance",
            symbols=["BTCUSDT"],
            products=["spot"],
            start=start,
            end=end,
        )
    )
    assert len(snaps) == 3
    assert snaps[0].bars[("binance", "BTCUSDT", "spot")].close == 60010.0
    assert snaps[2].bars[("binance", "BTCUSDT", "spot")].close == 60210.0


def test_loader_raises_when_no_data(tmp_path: Path) -> None:
    loader = BacktestLoader(parquet_root=tmp_path)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 31, tzinfo=UTC)
    with pytest.raises(BacktestDataError):
        list(
            loader.iter_snapshots(
                venue="binance",
                symbols=["BTCUSDT"],
                products=["spot"],
                start=start,
                end=end,
            )
        )
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/backtest/loader.py`:
```python
"""BacktestLoader — streams MarketSnapshot per bar from partitioned Parquet."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import polars as pl

from app.backtest.state import Bar, MarketSnapshot, Product
from app.market_data.duckdb_query import DuckDBQuery


class BacktestDataError(RuntimeError):
    """Raised when the requested backtest window has no underlying data."""


class BacktestLoader:
    """Loads Parquet partitions and yields MarketSnapshot objects bar-by-bar."""

    def __init__(self, *, parquet_root: Path) -> None:
        self._root = parquet_root
        self._query = DuckDBQuery(parquet_root=parquet_root)

    def iter_snapshots(
        self,
        *,
        venue: str,
        symbols: list[str],
        products: list[Product],
        start: datetime,
        end: datetime,
    ) -> Iterator[MarketSnapshot]:
        frames: dict[tuple[str, str, Product], pl.DataFrame] = {}
        for symbol in symbols:
            for product in products:
                df = self._query.klines(
                    exchange=venue, symbol=symbol, start=start, end=end
                )
                if df.height == 0:
                    continue
                frames[(venue, symbol, product)] = df

        if not frames:
            raise BacktestDataError(
                f"no data for {venue} {symbols} {products} in [{start}, {end}]"
            )

        # union of all bar timestamps across symbol/product combos
        all_ts: set[int] = set()
        for df in frames.values():
            all_ts.update(int(t) for t in df["ts_ms"].to_list())

        for ts_ms in sorted(all_ts):
            bars: dict[tuple[str, str, Product], Bar] = {}
            for key, df in frames.items():
                row = df.filter(pl.col("ts_ms") == ts_ms)
                if row.height == 0:
                    continue
                bars[key] = Bar(
                    ts_ms=int(row["ts_ms"][0]),
                    venue=key[0],
                    symbol=key[1],
                    product=key[2],
                    open=float(row["open"][0]),
                    high=float(row["high"][0]),
                    low=float(row["low"][0]),
                    close=float(row["close"][0]),
                    volume=float(row["volume"][0]),
                )
            yield MarketSnapshot(ts_ms=ts_ms, bars=bars)

    def load_funding(
        self,
        *,
        venue: str,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame | None:
        try:
            return self._query.funding_rates(
                exchange=venue, symbol=symbol, start=start, end=end
            )
        except Exception:
            return None
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_loader.py -v
git add backend/app/backtest/loader.py backend/tests/backtest/test_loader.py
git commit -m "feat: BacktestLoader streams MarketSnapshot from partitioned Parquet"
```

---

## Phase 4.4: Strategies + engine

### Task 11: Strategy Protocol + BuyAndHoldStrategy validator

**Files:**
- Create: `backend/app/backtest/strategies/__init__.py`
- Create: `backend/app/backtest/strategies/base.py`
- Create: `backend/app/backtest/strategies/buy_and_hold.py`
- Create: `backend/tests/backtest/test_buy_and_hold.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for BuyAndHoldStrategy — engine validator."""

from __future__ import annotations

from app.backtest.state import Bar, MarketSnapshot, MarketState
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy
from app.profile.defaults import PROFILE_SCOPED_DEFAULTS
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(values=dict(PROFILE_SCOPED_DEFAULTS))


def _state(positions: tuple = (), cash: float = 10_000.0) -> MarketState:
    bar = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="spot",
        open=60000.0, high=60050.0, low=59950.0, close=60010.0, volume=10.0,
    )
    return MarketState(
        snapshot=MarketSnapshot(ts_ms=1, bars={("binance", "BTCUSDT", "spot"): bar}),
        positions=positions,
        cash_quote=cash,
    )


def test_emits_buy_when_no_position() -> None:
    s = BuyAndHoldStrategy(venue="binance", symbol="BTCUSDT")
    orders = s.evaluate(_state(), _params())
    assert len(orders) == 1
    assert orders[0].side == "buy"
    assert orders[0].symbol == "BTCUSDT"
    assert orders[0].order_type == "market"


def test_emits_nothing_when_already_long() -> None:
    from app.backtest.state import Position

    s = BuyAndHoldStrategy(venue="binance", symbol="BTCUSDT")
    long = Position(venue="binance", symbol="BTCUSDT", product="spot", qty_base=0.16, avg_entry_px=60000.0)
    orders = s.evaluate(_state(positions=(long,)), _params())
    assert orders == []
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/backtest/strategies/__init__.py`:
```python
"""Backtest validator strategies — used to prove the engine plumbing.

Real strategies (funding arb, factor portfolio) ship in Phase 6+ under
``app.strategies/``. These are *engine validators*: minimal, deterministic,
designed to exercise specific engine features (P&L accumulation, hedge
pairs, funding accounting).
"""
```

`backend/app/backtest/strategies/base.py`:
```python
"""Strategy Protocol for the backtest engine. Same shape will be reused live."""

from __future__ import annotations

from typing import Protocol

from app.backtest.orders import Order
from app.backtest.state import MarketState
from app.profile.params import ProfileParams


class Strategy(Protocol):
    name: str

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]: ...
```

`backend/app/backtest/strategies/buy_and_hold.py`:
```python
"""BuyAndHoldStrategy — opens a single long position on first tick, holds forever.

Engine validator: exercises basic P&L accumulation. Sized via the registry
(``backtest.initial_cash_quote_usdc`` → buy ~that much notional at the first
available close).
"""

from __future__ import annotations

from app.backtest.orders import Order
from app.backtest.state import MarketState
from app.profile.params import ProfileParams


class BuyAndHoldStrategy:
    name = "buy_and_hold"

    def __init__(self, *, venue: str, symbol: str) -> None:
        self._venue = venue
        self._symbol = symbol

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        # If we already hold any position in this (venue, symbol, spot), do nothing.
        for pos in state.positions:
            if (pos.venue, pos.symbol, pos.product) == (self._venue, self._symbol, "spot"):
                return []
        # Initial buy sized by initial_cash_quote_usdc / current close.
        bar = state.snapshot.bars.get((self._venue, self._symbol, "spot"))
        if bar is None:
            return []
        notional = params.get("backtest.initial_cash_quote_usdc")
        assert isinstance(notional, (int, float))
        qty = float(notional) / bar.close
        return [
            Order(
                venue=self._venue,
                symbol=self._symbol,
                product="spot",
                side="buy",
                qty_base=qty,
                order_type="market",
            )
        ]
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_buy_and_hold.py -v
git add backend/app/backtest/strategies backend/tests/backtest/test_buy_and_hold.py
git commit -m "feat: Strategy Protocol + BuyAndHoldStrategy engine validator"
```

---

### Task 12: FundingArbSkeleton validator

**Files:**
- Create: `backend/app/backtest/strategies/funding_arb_skeleton.py`
- Create: `backend/tests/backtest/test_funding_arb_skeleton.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for FundingArbSkeleton — hedge-pair + funding engine validator."""

from __future__ import annotations

from app.backtest.state import Bar, MarketSnapshot, MarketState, Position
from app.backtest.strategies.funding_arb_skeleton import FundingArbSkeleton
from app.profile.defaults import PROFILE_SCOPED_DEFAULTS
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(values=dict(PROFILE_SCOPED_DEFAULTS))


def _state(positions: tuple = (), cash: float = 10_000.0) -> MarketState:
    spot_bar = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="spot",
        open=60000.0, high=60050.0, low=59950.0, close=60010.0, volume=10.0,
    )
    perp_bar = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="perp",
        open=60000.0, high=60050.0, low=59950.0, close=60010.0, volume=10.0,
    )
    return MarketState(
        snapshot=MarketSnapshot(
            ts_ms=1,
            bars={
                ("binance", "BTCUSDT", "spot"): spot_bar,
                ("binance", "BTCUSDT", "perp"): perp_bar,
            },
        ),
        positions=positions,
        cash_quote=cash,
    )


def test_emits_hedge_pair_when_no_position() -> None:
    s = FundingArbSkeleton(venue="binance", symbol="BTCUSDT")
    orders = s.evaluate(_state(), _params())
    assert len(orders) == 2
    spots = [o for o in orders if o.product == "spot"]
    perps = [o for o in orders if o.product == "perp"]
    assert len(spots) == 1
    assert len(perps) == 1
    assert spots[0].side == "buy"
    assert perps[0].side == "sell"
    # qty matches (delta neutral)
    assert spots[0].qty_base == perps[0].qty_base


def test_emits_nothing_when_already_hedged() -> None:
    s = FundingArbSkeleton(venue="binance", symbol="BTCUSDT")
    long_spot = Position(venue="binance", symbol="BTCUSDT", product="spot", qty_base=0.08, avg_entry_px=60000.0)
    short_perp = Position(venue="binance", symbol="BTCUSDT", product="perp", qty_base=-0.08, avg_entry_px=60000.0)
    orders = s.evaluate(_state(positions=(long_spot, short_perp)), _params())
    assert orders == []
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/backtest/strategies/funding_arb_skeleton.py`:
```python
"""FundingArbSkeleton — minimal delta-neutral validator (long spot + short perp).

Engine validator only. Real Strategy A (entry/exit logic, calibration,
capacity caps) lands in Phase 6.

Sizes the hedge pair using half of ``backtest.initial_cash_quote_usdc``
(spot leg notional). Hold-forever — opens once, never rebalances.
"""

from __future__ import annotations

from app.backtest.orders import Order
from app.backtest.state import MarketState
from app.profile.params import ProfileParams

_HEDGE_SIZE_FRACTION = 0.5


class FundingArbSkeleton:
    name = "funding_arb_skeleton"

    def __init__(self, *, venue: str, symbol: str) -> None:
        self._venue = venue
        self._symbol = symbol

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        has_spot = any(
            (p.venue, p.symbol, p.product) == (self._venue, self._symbol, "spot")
            for p in state.positions
        )
        has_perp = any(
            (p.venue, p.symbol, p.product) == (self._venue, self._symbol, "perp")
            for p in state.positions
        )
        if has_spot and has_perp:
            return []
        spot_bar = state.snapshot.bars.get((self._venue, self._symbol, "spot"))
        perp_bar = state.snapshot.bars.get((self._venue, self._symbol, "perp"))
        if spot_bar is None or perp_bar is None:
            return []
        initial_cash = params.get("backtest.initial_cash_quote_usdc")
        assert isinstance(initial_cash, (int, float))
        # Use half of initial cash for the spot leg notional; perp short at same qty.
        spot_notional = float(initial_cash) * _HEDGE_SIZE_FRACTION
        qty = spot_notional / spot_bar.close
        return [
            Order(
                venue=self._venue, symbol=self._symbol, product="spot",
                side="buy", qty_base=qty, order_type="market",
            ),
            Order(
                venue=self._venue, symbol=self._symbol, product="perp",
                side="sell", qty_base=qty, order_type="market",
            ),
        ]
```

Note: `_HEDGE_SIZE_FRACTION = 0.5` is a strategy-internal constant, not a tunable knob. Lint-wise we want it out of the AST literal scanner; per Constraint #1 only `engine.py`/`fills.py`/`funding.py`/`metrics.py` + strategy files in `strategies/` are scanned. Since `funding_arb_skeleton.py` IS a strategy file, the constant must go into the registry too. Move it: add `backtest.funding_arb_skeleton.hedge_size_fraction: 0.5` to `PROFILE_SCOPED_DEFAULTS` in `defaults.py`, and read it via `params.get(...)` in the strategy.

Updated strategy body (read from registry):
```python
def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
    has_spot = any(
        (p.venue, p.symbol, p.product) == (self._venue, self._symbol, "spot")
        for p in state.positions
    )
    has_perp = any(
        (p.venue, p.symbol, p.product) == (self._venue, self._symbol, "perp")
        for p in state.positions
    )
    if has_spot and has_perp:
        return []
    spot_bar = state.snapshot.bars.get((self._venue, self._symbol, "spot"))
    perp_bar = state.snapshot.bars.get((self._venue, self._symbol, "perp"))
    if spot_bar is None or perp_bar is None:
        return []
    initial_cash = params.get("backtest.initial_cash_quote_usdc")
    fraction = params.get("backtest.funding_arb_skeleton.hedge_size_fraction")
    assert isinstance(initial_cash, (int, float))
    assert isinstance(fraction, (int, float))
    spot_notional = float(initial_cash) * float(fraction)
    qty = spot_notional / spot_bar.close
    return [
        Order(
            venue=self._venue, symbol=self._symbol, product="spot",
            side="buy", qty_base=qty, order_type="market",
        ),
        Order(
            venue=self._venue, symbol=self._symbol, product="perp",
            side="sell", qty_base=qty, order_type="market",
        ),
    ]
```

Drop the module-level `_HEDGE_SIZE_FRACTION` constant.

Also update `backend/app/profile/defaults.py`:
```python
"backtest.funding_arb_skeleton.hedge_size_fraction": 0.5,
```

And append to `backend/tests/test_profile_registry.py`:
```python
def test_funding_arb_skeleton_fraction_key_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS
    assert PROFILE_SCOPED_DEFAULTS["backtest.funding_arb_skeleton.hedge_size_fraction"] == 0.5
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_funding_arb_skeleton.py tests/test_profile_registry.py -v
git add backend/app/backtest/strategies/funding_arb_skeleton.py backend/app/profile/defaults.py backend/tests/backtest/test_funding_arb_skeleton.py backend/tests/test_profile_registry.py
git commit -m "feat: FundingArbSkeleton hedge-pair validator + registry key"
```

---

### Task 13: Engine event loop

**Files:**
- Create: `backend/app/backtest/engine.py`
- Create: `backend/tests/backtest/test_engine.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for backtest Engine — event loop integrating loader + strategy + fills + funding."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from app.backtest.engine import Engine
from app.backtest.loader import BacktestDataError, BacktestLoader
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy
from app.market_data.parquet_store import ParquetStore
from app.profile.defaults import PROFILE_SCOPED_DEFAULTS
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(values=dict(PROFILE_SCOPED_DEFAULTS))


def _write_klines(store: ParquetStore) -> int:
    # Three 1m bars: 60000 → 60100 → 60200
    base = 1704067200000
    df = pl.DataFrame(
        {
            "ts_ms": [base, base + 60_000, base + 120_000],
            "open": [60000.0, 60100.0, 60200.0],
            "high": [60050.0, 60150.0, 60250.0],
            "low": [59950.0, 60050.0, 60150.0],
            "close": [60000.0, 60100.0, 60200.0],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=2024, month=1)
    return base


def test_buy_and_hold_equity_curve_matches_hand_computation(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
    _write_klines(store)
    loader = BacktestLoader(parquet_root=tmp_path)
    strategy = BuyAndHoldStrategy(venue="binance", symbol="BTCUSDT")
    params = _params()
    engine = Engine(loader=loader, strategy=strategy, params=params)
    start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 2, tzinfo=UTC)
    result = engine.run(venue="binance", symbols=["BTCUSDT"], products=["spot"], start=start, end=end)

    assert result.equity_curve.height == 3
    # Tick 1: buy 10000 USDC of BTC at 60000 (+5bps slippage = 60030). Fee = 10 bps.
    # qty = 10000 / 60000 = 0.16666...; cost = 0.16666 * 60030 + fee
    # Equity after fill ≈ initial_cash (slight loss to fee + slippage).
    # By Tick 3 the BTC mark is 60200; equity = qty * 60200 + remaining cash
    equity_curve = result.equity_curve["equity"].to_list()
    assert equity_curve[2] > equity_curve[0]  # price went up → equity up


def test_engine_raises_on_missing_data(tmp_path: Path) -> None:
    loader = BacktestLoader(parquet_root=tmp_path)
    strategy = BuyAndHoldStrategy(venue="binance", symbol="BTCUSDT")
    engine = Engine(loader=loader, strategy=strategy, params=_params())
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 31, tzinfo=UTC)
    with pytest.raises(BacktestDataError):
        engine.run(venue="binance", symbols=["BTCUSDT"], products=["spot"], start=start, end=end)


def test_zero_orders_per_tick_produces_flat_curve(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
    _write_klines(store)
    loader = BacktestLoader(parquet_root=tmp_path)

    class NullStrategy:
        name = "null"
        def evaluate(self, state, params):  # type: ignore[no-untyped-def]
            return []

    params = _params()
    engine = Engine(loader=loader, strategy=NullStrategy(), params=params)
    start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 2, tzinfo=UTC)
    result = engine.run(venue="binance", symbols=["BTCUSDT"], products=["spot"], start=start, end=end)

    initial = params.get("backtest.initial_cash_quote_usdc")
    assert all(e == float(initial) for e in result.equity_curve["equity"].to_list())
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/backtest/engine.py`:
```python
"""Engine — event loop walking MarketSnapshots from BacktestLoader.

Calls strategy.evaluate(state, params), applies fills, applies funding,
yields an equity-curve Polars DataFrame.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import polars as pl

from app.backtest.fills import FillSimulator, InsufficientCashError
from app.backtest.funding import FundingLedger
from app.backtest.loader import BacktestLoader
from app.backtest.positions import PositionBook
from app.backtest.state import MarketState, Product
from app.backtest.strategies.base import Strategy
from app.profile.params import ProfileParams


@dataclass
class BacktestResult:
    equity_curve: pl.DataFrame  # ts_ms / equity / cash / num_open_positions
    num_trades: int


class Engine:
    def __init__(
        self,
        *,
        loader: BacktestLoader,
        strategy: Strategy,
        params: ProfileParams,
    ) -> None:
        self._loader = loader
        self._strategy = strategy
        self._params = params

    def run(
        self,
        *,
        venue: str,
        symbols: list[str],
        products: list[Product],
        start: datetime,
        end: datetime,
    ) -> BacktestResult:
        initial_cash = self._params.get("backtest.initial_cash_quote_usdc")
        assert isinstance(initial_cash, (int, float))
        cash: float = float(initial_cash)
        book = PositionBook()
        fill_sim = FillSimulator(params=self._params)
        funding = FundingLedger()

        # preload funding data per (venue, symbol)
        funding_data = {}
        for symbol in symbols:
            df = self._loader.load_funding(venue=venue, symbol=symbol, start=start, end=end)
            if df is not None and df.height > 0:
                funding_data[(venue, symbol)] = df

        rows_ts: list[int] = []
        rows_equity: list[float] = []
        rows_cash: list[float] = []
        rows_open: list[int] = []
        num_trades = 0

        for snapshot in self._loader.iter_snapshots(
            venue=venue, symbols=symbols, products=products, start=start, end=end
        ):
            # 1) Apply funding for any open perp positions at this ts
            mark_pxs = {k: bar.close for k, bar in snapshot.bars.items()}
            events = funding.events_for(
                positions=book.snapshot(),
                ts_ms=snapshot.ts_ms,
                funding_data=funding_data,
                mark_pxs=mark_pxs,
            )
            for event in events:
                cash += event.payment_quote

            # 2) Build state, call strategy
            state = MarketState(
                snapshot=snapshot,
                positions=book.snapshot(),
                cash_quote=cash,
            )
            orders = self._strategy.evaluate(state, self._params)

            # 3) Apply fills (skip and continue on cash errors)
            if orders:
                try:
                    fills, cash = fill_sim.fill(orders, snapshot, cash=cash)
                    book.apply(fills)
                    num_trades += len(fills)
                except InsufficientCashError:
                    pass

            # 4) Mark-to-market → record point on equity curve
            mtm = book.mark_to_market(snapshot)
            equity = cash + mtm
            rows_ts.append(snapshot.ts_ms)
            rows_equity.append(equity)
            rows_cash.append(cash)
            rows_open.append(len(book.snapshot()))

        equity_curve = pl.DataFrame(
            {
                "ts_ms": rows_ts,
                "equity": rows_equity,
                "cash": rows_cash,
                "num_open_positions": rows_open,
            }
        )
        return BacktestResult(equity_curve=equity_curve, num_trades=num_trades)
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_engine.py -v
git add backend/app/backtest/engine.py backend/tests/backtest/test_engine.py
git commit -m "feat: backtest engine event loop integrating loader + strategy + fills + funding"
```

---

### Task 14: Runner — high-level entry point

**Files:**
- Create: `backend/app/backtest/runner.py`
- Create: `backend/tests/backtest/test_runner.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for backtest runner — high-level entry that returns BacktestResult + metrics."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from app.backtest.runner import RunOptions, run_backtest
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy
from app.market_data.parquet_store import ParquetStore
from app.profile.defaults import PROFILE_SCOPED_DEFAULTS
from app.profile.params import ProfileParams


def test_runner_returns_metrics(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
    base = 1704067200000
    df = pl.DataFrame(
        {
            "ts_ms": [base, base + 60_000, base + 120_000],
            "open": [60000.0, 60100.0, 60200.0],
            "high": [60050.0, 60150.0, 60250.0],
            "low": [59950.0, 60050.0, 60150.0],
            "close": [60000.0, 60100.0, 60200.0],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=2024, month=1)

    params = ProfileParams(values=dict(PROFILE_SCOPED_DEFAULTS))
    strategy = BuyAndHoldStrategy(venue="binance", symbol="BTCUSDT")
    opts = RunOptions(
        venue="binance",
        symbols=["BTCUSDT"],
        products=["spot"],
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 1, 0, 2, tzinfo=UTC),
    )
    result = run_backtest(
        parquet_root=tmp_path,
        strategy=strategy,
        params=params,
        options=opts,
    )
    assert result.metrics.num_trades >= 1
    assert result.equity_curve.height == 3
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/backtest/runner.py`:
```python
"""run_backtest — high-level glue from inputs to BacktestRunResult."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

from app.backtest.engine import Engine
from app.backtest.loader import BacktestLoader
from app.backtest.metrics import BacktestMetrics, compute_metrics
from app.backtest.state import Product
from app.backtest.strategies.base import Strategy
from app.profile.params import ProfileParams


@dataclass(frozen=True)
class RunOptions:
    venue: str
    symbols: list[str]
    products: list[Product]
    start: datetime
    end: datetime


@dataclass
class BacktestRunResult:
    equity_curve: pl.DataFrame
    metrics: BacktestMetrics


def run_backtest(
    *,
    parquet_root: Path,
    strategy: Strategy,
    params: ProfileParams,
    options: RunOptions,
) -> BacktestRunResult:
    loader = BacktestLoader(parquet_root=parquet_root)
    engine = Engine(loader=loader, strategy=strategy, params=params)
    engine_result = engine.run(
        venue=options.venue,
        symbols=options.symbols,
        products=options.products,
        start=options.start,
        end=options.end,
    )
    metrics = compute_metrics(
        engine_result.equity_curve, params=params, num_trades=engine_result.num_trades
    )
    return BacktestRunResult(
        equity_curve=engine_result.equity_curve, metrics=metrics
    )
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_runner.py -v
git add backend/app/backtest/runner.py backend/tests/backtest/test_runner.py
git commit -m "feat: run_backtest high-level entry returning BacktestRunResult"
```

---

## Phase 4.5: API + worker

### Task 15: Strategy registry

**Files:**
- Create: `backend/app/backtest/registry.py`
- Create: `backend/tests/backtest/test_registry.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for backtest strategy registry — name → Strategy factory."""

from __future__ import annotations

import pytest

from app.backtest.registry import StrategyRegistry, UnknownStrategy


def test_resolve_buy_and_hold() -> None:
    reg = StrategyRegistry.default()
    s = reg.build("buy_and_hold", venue="binance", symbol="BTCUSDT")
    assert s.name == "buy_and_hold"


def test_resolve_funding_arb_skeleton() -> None:
    reg = StrategyRegistry.default()
    s = reg.build("funding_arb_skeleton", venue="binance", symbol="BTCUSDT")
    assert s.name == "funding_arb_skeleton"


def test_unknown_strategy_raises() -> None:
    reg = StrategyRegistry.default()
    with pytest.raises(UnknownStrategy):
        reg.build("does_not_exist", venue="binance", symbol="BTCUSDT")
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/backtest/registry.py`:
```python
"""Strategy registry — name → Strategy factory.

The API endpoint validates ``strategy_name`` against this registry; the
worker job looks it up to construct the strategy instance.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.backtest.strategies.base import Strategy
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy
from app.backtest.strategies.funding_arb_skeleton import FundingArbSkeleton


class UnknownStrategy(KeyError):
    """Raised when a strategy_name isn't registered."""


class StrategyRegistry:
    def __init__(
        self, factories: dict[str, Callable[..., Strategy]]
    ) -> None:
        self._factories = factories

    @classmethod
    def default(cls) -> "StrategyRegistry":
        return cls(
            {
                "buy_and_hold": lambda **kw: BuyAndHoldStrategy(**kw),
                "funding_arb_skeleton": lambda **kw: FundingArbSkeleton(**kw),
            }
        )

    def names(self) -> list[str]:
        return sorted(self._factories.keys())

    def build(self, name: str, **kwargs: Any) -> Strategy:
        if name not in self._factories:
            raise UnknownStrategy(name)
        return self._factories[name](**kwargs)
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_registry.py -v
git add backend/app/backtest/registry.py backend/tests/backtest/test_registry.py
git commit -m "feat: backtest StrategyRegistry name → factory"
```

---

### Task 16: BacktestService — apply profile + run + persist

**Files:**
- Create: `backend/app/services/backtest_service.py`
- Create: `backend/tests/services/test_backtest_service.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for BacktestService — persists run lifecycle + writes equity curve Parquet."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.parquet_store import ParquetStore
from app.models.backtest_run import BacktestRun
from app.models.strategy_profile import StrategyProfile
from app.services.backtest_service import BacktestService


def _canonical_json(d: dict) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


def _profile_hash(parameters: dict) -> str:
    return hashlib.sha256(_canonical_json(parameters).encode()).hexdigest()


def _write_klines(root: Path) -> None:
    store = ParquetStore(root=root)
    base = 1704067200000
    df = pl.DataFrame(
        {
            "ts_ms": [base, base + 60_000, base + 120_000],
            "open": [60000.0, 60100.0, 60200.0],
            "high": [60050.0, 60150.0, 60250.0],
            "low": [59950.0, 60050.0, 60150.0],
            "close": [60000.0, 60100.0, 60200.0],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=2024, month=1)


@pytest.mark.asyncio
async def test_run_persists_and_writes_curve(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _write_klines(parquet_root)
    curves_root = tmp_path / "backtest_runs"

    profile = StrategyProfile(
        name="test-profile",
        version=1,
        is_active=False,
        parameters={},
    )
    db_session.add(profile)
    await db_session.flush()

    run = BacktestRun(
        profile_id=profile.id,
        profile_version=profile.version,
        profile_hash=_profile_hash(profile.parameters),
        strategy_name="buy_and_hold",
        venue="binance",
        symbols=["BTCUSDT"],
        start_ts=datetime(2024, 1, 1, tzinfo=UTC),
        end_ts=datetime(2024, 1, 1, 0, 2, tzinfo=UTC),
        status="pending",
    )
    db_session.add(run)
    await db_session.flush()
    run_id = run.id

    service = BacktestService(
        session=db_session,
        parquet_root=parquet_root,
        backtest_curves_root=curves_root,
    )
    await service.execute(run_id)

    await db_session.refresh(run)
    assert run.status == "complete"
    assert run.num_trades is not None
    assert run.equity_curve_path is not None
    assert (curves_root / f"{run_id}.parquet").exists()


@pytest.mark.asyncio
async def test_run_marks_failed_on_no_data(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    curves_root = tmp_path / "backtest_runs"

    profile = StrategyProfile(name="empty-profile", version=1, is_active=False, parameters={})
    db_session.add(profile)
    await db_session.flush()

    run = BacktestRun(
        profile_id=profile.id,
        profile_version=profile.version,
        profile_hash=_profile_hash(profile.parameters),
        strategy_name="buy_and_hold",
        venue="binance",
        symbols=["BTCUSDT"],
        start_ts=datetime(2024, 1, 1, tzinfo=UTC),
        end_ts=datetime(2024, 1, 31, tzinfo=UTC),
        status="pending",
    )
    db_session.add(run)
    await db_session.flush()

    service = BacktestService(
        session=db_session, parquet_root=parquet_root, backtest_curves_root=curves_root,
    )
    with pytest.raises(Exception):  # re-raised after marking failed
        await service.execute(run.id)
    await db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_message is not None
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/services/backtest_service.py`:
```python
"""BacktestService — orchestrates execute(run_id) for the worker job.

Lifecycle: pending → running → (complete | failed).
Writes the equity curve as Parquet at ``<curves_root>/<run_id>.parquet``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.registry import StrategyRegistry
from app.backtest.runner import RunOptions, run_backtest
from app.models.backtest_run import BacktestRun
from app.models.strategy_profile import StrategyProfile
from app.profile.params import ProfileParams


class BacktestService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        parquet_root: Path,
        backtest_curves_root: Path,
        registry: StrategyRegistry | None = None,
    ) -> None:
        self._session = session
        self._parquet_root = parquet_root
        self._curves_root = backtest_curves_root
        self._registry = registry or StrategyRegistry.default()

    async def execute(self, run_id: uuid.UUID) -> None:
        run = await self._load(run_id)
        try:
            run.status = "running"
            run.started_at = datetime.now(UTC)
            await self._session.flush()

            profile = await self._load_profile(run.profile_id)
            params = ProfileParams.from_profile_parameters(profile.parameters)

            # First symbol is the validator symbol for these stub strategies
            symbol = run.symbols[0]
            strategy = self._registry.build(
                run.strategy_name, venue=run.venue, symbol=symbol
            )
            products = ["spot", "perp"] if run.strategy_name == "funding_arb_skeleton" else ["spot"]
            opts = RunOptions(
                venue=run.venue,
                symbols=run.symbols,
                products=products,
                start=run.start_ts,
                end=run.end_ts,
            )
            result = run_backtest(
                parquet_root=self._parquet_root,
                strategy=strategy,
                params=params,
                options=opts,
            )

            self._curves_root.mkdir(parents=True, exist_ok=True)
            curve_path = self._curves_root / f"{run_id}.parquet"
            result.equity_curve.write_parquet(curve_path, compression="zstd")

            run.status = "complete"
            run.completed_at = datetime.now(UTC)
            run.total_return = result.metrics.total_return
            run.sharpe = result.metrics.sharpe
            run.max_drawdown = result.metrics.max_drawdown
            run.num_trades = result.metrics.num_trades
            run.equity_curve_path = str(curve_path)
            await self._session.flush()
        except Exception as e:
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            run.error_message = f"{type(e).__name__}: {e}"
            await self._session.flush()
            raise

    async def _load(self, run_id: uuid.UUID) -> BacktestRun:
        result = await self._session.execute(
            select(BacktestRun).where(BacktestRun.id == run_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise KeyError(f"backtest run {run_id} not found")
        return row

    async def _load_profile(self, profile_id: uuid.UUID) -> StrategyProfile:
        result = await self._session.execute(
            select(StrategyProfile).where(StrategyProfile.id == profile_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise KeyError(f"profile {profile_id} not found")
        return profile
```

**Note:** `ProfileParams.from_profile_parameters(profile.parameters)` may not exist yet — check `backend/app/profile/params.py`. If absent, add the factory:

```python
@classmethod
def from_profile_parameters(cls, parameters: dict) -> "ProfileParams":
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS
    merged = dict(PROFILE_SCOPED_DEFAULTS)
    merged.update(parameters)
    return cls(values=merged)
```

(Adjust to match the existing `ProfileParams` constructor signature; the test in Task 11 uses `ProfileParams(values=...)` which implies the constructor accepts a `values=` kwarg — match the existing pattern.)

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/services/test_backtest_service.py -v
git add backend/app/services/backtest_service.py backend/app/profile/params.py backend/tests/services/test_backtest_service.py
git commit -m "feat: BacktestService executes run with audit-locked profile + persists results"
```

---

### Task 17: Worker run_backtest job

**Files:**
- Modify: `backend/app/worker/main.py`
- Create: `backend/app/worker/jobs/run_backtest.py`
- Modify: `backend/tests/test_worker_jobs.py`

- [ ] **Step 1: Failing test (append to `test_worker_jobs.py`)**

```python
@pytest.mark.asyncio
async def test_run_backtest_dispatches() -> None:
    from app.worker.main import _resolve_job

    job = _resolve_job("run_backtest")
    assert callable(job)


@pytest.mark.asyncio
async def test_run_backtest_requires_backtest_id_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BACKTEST_ID", raising=False)
    from app.worker.jobs.run_backtest import run

    with pytest.raises(KeyError, match="BACKTEST_ID"):
        await run()
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement**

`backend/app/worker/jobs/run_backtest.py`:
```python
"""Worker job — execute a queued BacktestRun by id."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import async_session_factory
from app.services.backtest_service import BacktestService

logger = logging.getLogger(__name__)

_DEFAULT_PARQUET_ROOT = Path("data/parquet")
_DEFAULT_CURVES_ROOT = Path("data/backtest_runs")


async def run_with(
    *,
    session: AsyncSession,
    run_id: uuid.UUID,
    parquet_root: Path,
    curves_root: Path,
) -> None:
    service = BacktestService(
        session=session,
        parquet_root=parquet_root,
        backtest_curves_root=curves_root,
    )
    await service.execute(run_id)


async def run() -> None:
    raw_id = os.environ.get("BACKTEST_ID")
    if not raw_id:
        raise KeyError("BACKTEST_ID env var required for run_backtest job")
    run_id = uuid.UUID(raw_id)
    parquet_root = Path(os.environ.get("BACKTEST_PARQUET_ROOT", str(_DEFAULT_PARQUET_ROOT)))
    curves_root = Path(os.environ.get("BACKTEST_CURVES_ROOT", str(_DEFAULT_CURVES_ROOT)))

    async with async_session_factory() as session:
        await run_with(
            session=session,
            run_id=run_id,
            parquet_root=parquet_root,
            curves_root=curves_root,
        )
        await session.commit()
    logger.info("run_backtest complete", extra={"backtest_id": str(run_id)})
```

(Adjust `async_session_factory` import path to match Phase 1+2's existing helper; read `backend/app/deps.py` to confirm name.)

Modify `backend/app/worker/main.py` `_JOBS` dict:
```python
from app.worker.jobs import refresh_data, run_backtest

_JOBS: dict[str, Callable[[], Coroutine[Any, Any, None]]] = {
    "refresh_data": refresh_data.run,
    "run_backtest": run_backtest.run,
}
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/test_worker_jobs.py -v
git add backend/app/worker backend/tests/test_worker_jobs.py
git commit -m "feat: run_backtest worker job invokes BacktestService"
```

---

### Task 18: docker-compose worker-run-backtest + justfile recipe

**Files:**
- Modify: `docker-compose.yml`
- Modify: `justfile`

- [ ] **Step 1: Append service to `docker-compose.yml`** (after `worker-refresh-data:`)

```yaml
  worker-run-backtest:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: cryptobot-worker-run-backtest
    restart: "no"
    command: uv run python -m app.worker.main
    environment:
      WORKER_JOB: run_backtest
      BACKTEST_ID: ${BACKTEST_ID:?BACKTEST_ID is required}
      DATABASE_URL: postgresql+asyncpg://cryptobot:${POSTGRES_PASSWORD:-devpass}@postgres:5432/cryptobot
      DATABASE_URL_SYNC: postgresql+psycopg://cryptobot:${POSTGRES_PASSWORD:-devpass}@postgres:5432/cryptobot
    volumes:
      - ./data:/app/data
    depends_on:
      postgres:
        condition: service_healthy
    profiles: ["jobs"]
```

(Match the indentation of `worker-refresh-data`. The `volumes:` line mounts `./data` so the worker can write equity-curve Parquet files visible on host.)

- [ ] **Step 2: Verify YAML still parses**

```bash
BACKTEST_ID=dummy docker compose --profile jobs config --quiet
```
Expected: exits 0.

- [ ] **Step 3: Add `just backtest` recipe** — append to `justfile`:

```just

# Run a single backtest by id (uses WORKER_JOB=run_backtest)
backtest BACKTEST_ID:
    cd backend && WORKER_JOB=run_backtest BACKTEST_ID={{BACKTEST_ID}} uv run python -m app.worker.main
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml justfile
git commit -m "chore: docker-compose worker-run-backtest + just backtest recipe"
```

---

### Task 19: API — POST + GET /api/v1/backtests

**Files:**
- Create: `backend/app/api/backtests.py`
- Create: `backend/app/schemas/backtest.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_backtests.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for /api/v1/backtests endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.parquet_store import ParquetStore
from app.models.strategy_profile import StrategyProfile


def _write_klines(root: Path) -> None:
    store = ParquetStore(root=root)
    base = 1704067200000
    df = pl.DataFrame(
        {
            "ts_ms": [base, base + 60_000, base + 120_000],
            "open": [60000.0, 60100.0, 60200.0],
            "high": [60050.0, 60150.0, 60250.0],
            "low": [59950.0, 60050.0, 60150.0],
            "close": [60000.0, 60100.0, 60200.0],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=2024, month=1)


@pytest.mark.asyncio
async def test_post_creates_pending_row(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _write_klines(parquet_root)
    monkeypatch.setenv("BACKTEST_PARQUET_ROOT", str(parquet_root))

    profile = StrategyProfile(name="test", version=1, is_active=False, parameters={})
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    body = {
        "profile_id": str(profile.id),
        "strategy_name": "buy_and_hold",
        "start_ts": "2024-01-01T00:00:00Z",
        "end_ts": "2024-01-01T00:02:00Z",
        "venue": "binance",
        "symbols": ["BTCUSDT"],
    }
    r = await async_client.post("/api/v1/backtests", json=body)
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "pending"
    assert "id" in data


@pytest.mark.asyncio
async def test_get_returns_row(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _write_klines(parquet_root)
    monkeypatch.setenv("BACKTEST_PARQUET_ROOT", str(parquet_root))

    profile = StrategyProfile(name="t2", version=1, is_active=False, parameters={})
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    body = {
        "profile_id": str(profile.id),
        "strategy_name": "buy_and_hold",
        "start_ts": "2024-01-01T00:00:00Z",
        "end_ts": "2024-01-01T00:02:00Z",
        "venue": "binance",
        "symbols": ["BTCUSDT"],
    }
    r = await async_client.post("/api/v1/backtests", json=body)
    run_id = r.json()["id"]
    g = await async_client.get(f"/api/v1/backtests/{run_id}")
    assert g.status_code == 200
    assert g.json()["id"] == run_id


@pytest.mark.asyncio
async def test_post_rejects_unknown_strategy(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    profile = StrategyProfile(name="t3", version=1, is_active=False, parameters={})
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    body = {
        "profile_id": str(profile.id),
        "strategy_name": "nope",
        "start_ts": "2024-01-01T00:00:00Z",
        "end_ts": "2024-01-01T00:02:00Z",
        "venue": "binance",
        "symbols": ["BTCUSDT"],
    }
    r = await async_client.post("/api/v1/backtests", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_unknown_profile(
    async_client: AsyncClient,
) -> None:
    import uuid as _uuid

    body = {
        "profile_id": str(_uuid.uuid4()),
        "strategy_name": "buy_and_hold",
        "start_ts": "2024-01-01T00:00:00Z",
        "end_ts": "2024-01-01T00:02:00Z",
        "venue": "binance",
        "symbols": ["BTCUSDT"],
    }
    r = await async_client.post("/api/v1/backtests", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_missing_returns_404(async_client: AsyncClient) -> None:
    import uuid as _uuid

    r = await async_client.get(f"/api/v1/backtests/{_uuid.uuid4()}")
    assert r.status_code == 404
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implement schemas + router**

`backend/app/schemas/backtest.py`:
```python
"""Pydantic v2 schemas for backtest endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator


class CreateBacktestRequest(BaseModel):
    profile_id: uuid.UUID
    strategy_name: Annotated[str, Field(min_length=1, max_length=80)]
    start_ts: datetime
    end_ts: datetime
    venue: Annotated[str, Field(min_length=1, max_length=40)]
    symbols: Annotated[list[str], Field(min_length=1, max_length=200)]

    @field_validator("end_ts")
    @classmethod
    def _end_after_start(cls, v: datetime, info) -> datetime:  # type: ignore[no-untyped-def]
        start = info.data.get("start_ts")
        if start is not None and v <= start:
            raise ValueError("end_ts must be after start_ts")
        return v


class BacktestResponse(BaseModel):
    id: uuid.UUID
    profile_id: uuid.UUID
    profile_version: int
    profile_hash: str
    strategy_name: str
    venue: str
    symbols: list[str]
    start_ts: datetime
    end_ts: datetime
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    total_return: float | None
    sharpe: float | None
    max_drawdown: float | None
    num_trades: int | None
    equity_curve_path: str | None
    error_message: str | None
    created_at: datetime
```

`backend/app/api/backtests.py`:
```python
"""HTTP API for backtest run orchestration."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.registry import StrategyRegistry
from app.deps import get_db
from app.models.backtest_run import BacktestRun
from app.models.strategy_profile import StrategyProfile
from app.schemas.backtest import BacktestResponse, CreateBacktestRequest

router = APIRouter(prefix="/api/v1/backtests", tags=["backtests"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

_DEFAULT_LIMIT = 50


def _canonical_profile_hash(parameters: dict) -> str:
    return hashlib.sha256(
        json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@router.post("", response_model=BacktestResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_backtest(
    body: CreateBacktestRequest, db: DbSession
) -> BacktestResponse:
    # 1. Validate profile exists
    p_result = await db.execute(
        select(StrategyProfile).where(StrategyProfile.id == body.profile_id)
    )
    profile = p_result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown profile_id")

    # 2. Validate strategy name
    registry = StrategyRegistry.default()
    if body.strategy_name not in registry.names():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown strategy_name: {body.strategy_name}",
        )

    # 3. Compute profile_hash and insert pending row
    run = BacktestRun(
        profile_id=profile.id,
        profile_version=profile.version,
        profile_hash=_canonical_profile_hash(profile.parameters),
        strategy_name=body.strategy_name,
        venue=body.venue,
        symbols=body.symbols,
        start_ts=body.start_ts,
        end_ts=body.end_ts,
        status="pending",
    )
    db.add(run)
    await db.flush()
    await db.commit()
    await db.refresh(run)
    return BacktestResponse.model_validate(run, from_attributes=True)


@router.get("/{run_id}", response_model=BacktestResponse)
async def get_backtest(run_id: uuid.UUID, db: DbSession) -> BacktestResponse:
    result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "backtest run not found")
    return BacktestResponse.model_validate(row, from_attributes=True)


@router.get("", response_model=list[BacktestResponse])
async def list_backtests(
    db: DbSession,
    limit: int = _DEFAULT_LIMIT,
    profile_id: uuid.UUID | None = None,
    strategy_name: str | None = None,
    status_filter: str | None = None,
) -> list[BacktestResponse]:
    stmt = select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(limit)
    if profile_id is not None:
        stmt = stmt.where(BacktestRun.profile_id == profile_id)
    if strategy_name is not None:
        stmt = stmt.where(BacktestRun.strategy_name == strategy_name)
    if status_filter is not None:
        stmt = stmt.where(BacktestRun.status == status_filter)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return [BacktestResponse.model_validate(r, from_attributes=True) for r in rows]
```

Modify `backend/app/main.py` to register the router:
```python
from app.api import backtests, data_health, health, strategy_profiles
# ...
app.include_router(backtests.router)
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/api/test_backtests.py -v
git add backend/app/api/backtests.py backend/app/schemas/backtest.py backend/app/main.py backend/tests/api/test_backtests.py
git commit -m "feat: POST + GET /api/v1/backtests endpoints"
```

---

## Phase 4.6: Audit trail + lint + smoke + docs

### Task 20: Audit-trail test (Constraint #4)

**Files:**
- Create: `backend/tests/backtest/test_audit_trail.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for backtest audit trail — profile_hash must be sha256 of params at creation."""

from __future__ import annotations

import hashlib
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.backtest_run import BacktestRun
from app.models.strategy_profile import StrategyProfile


def _canonical_hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.asyncio
async def test_profile_hash_locks_at_creation(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    profile = StrategyProfile(name="audit-test", version=1, is_active=False, parameters={"x": 1})
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    body = {
        "profile_id": str(profile.id),
        "strategy_name": "buy_and_hold",
        "start_ts": "2024-01-01T00:00:00Z",
        "end_ts": "2024-01-01T00:02:00Z",
        "venue": "binance",
        "symbols": ["BTCUSDT"],
    }
    r = await async_client.post("/api/v1/backtests", json=body)
    run_id = r.json()["id"]
    expected = _canonical_hash({"x": 1})
    assert r.json()["profile_hash"] == expected

    # Mutate the profile AFTER the run is created
    profile.parameters = {"x": 9999}
    profile.version = 2
    await db_session.flush()
    await db_session.commit()

    # The BacktestRun's hash MUST be unchanged
    db_row = (
        await db_session.execute(
            select(BacktestRun).where(BacktestRun.id == run_id)
        )
    ).scalar_one()
    assert db_row.profile_hash == expected
    assert db_row.profile_version == 1
```

- [ ] **Step 2: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_audit_trail.py -v
git add backend/tests/backtest/test_audit_trail.py
git commit -m "test: backtest audit trail locks profile_hash at row creation"
```

---

### Task 21: Extend AST literal lint to backtest/

**Files:**
- Modify: `scripts/lint_no_literals_in_strategies.py`
- Modify: `backend/tests/test_ast_lint.py`

- [ ] **Step 1: Read the existing AST lint script** to see the file-target list:

```bash
cat scripts/lint_no_literals_in_strategies.py
```

- [ ] **Step 2: Extend the target list**

Modify the file's target glob/list to include:
- `backend/app/backtest/engine.py`
- `backend/app/backtest/fills.py`
- `backend/app/backtest/funding.py`
- `backend/app/backtest/metrics.py`
- `backend/app/backtest/strategies/**/*.py`

(The exact mechanism depends on the existing script. It may be a list of paths, a glob, or a directory walker — modify in place to add these. If it's a directory walker, add `backend/app/backtest/` and `backend/app/backtest/strategies/` as scanned roots, with the existing exception list (constants like `_BPS_DIVISOR`, `_HEDGE_SIZE_FRACTION`-style module constants that survived this plan's refactor) explicitly OK.)

- [ ] **Step 3: Run the lint**

```bash
python3 scripts/lint_no_literals_in_strategies.py
```
Expected: clean. If it trips on a literal, either:
- Move that literal to the registry (preferred — adds a new key to `defaults.py`)
- Add a documented module-level constant exemption (only for true unit-of-measure constants like `_BPS_DIVISOR = 10_000.0`)

- [ ] **Step 4: Extend `tests/test_ast_lint.py`** to assert no literals in the new files

If the existing test parameterises over a list of "monitored" files, append the new ones. If it scans a directory, no changes needed. Verify with:

```bash
cd backend && uv run pytest tests/test_ast_lint.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lint_no_literals_in_strategies.py backend/tests/test_ast_lint.py
git commit -m "chore: extend AST literal lint to backtest engine + strategies"
```

---

### Task 22: End-to-end smoke + README

**Files:**
- Create: `backend/tests/integration/test_backtest_smoke.py`
- Modify: `README.md`

- [ ] **Step 1: Marker-gated smoke test**

`backend/tests/integration/test_backtest_smoke.py`:
```python
"""Integration smoke: BuyAndHold over Binance Vision BTCUSDT 2024-01.

Marked ``slow`` (deselected by default). Requires:
  1. Phase 3 data refresh has populated data/parquet/binance/BTCUSDT/kline_1m/2024/01.parquet
  2. Postgres up + migrated to 0003

Run via: cd backend && uv run pytest -m slow tests/integration/test_backtest_smoke.py -v
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.parquet_store import DataType, ParquetStore
from app.models.strategy_profile import StrategyProfile
from app.services.backtest_service import BacktestService


@pytest.mark.slow
@pytest.mark.asyncio
async def test_smoke_buy_and_hold_btcusdt_jan_2024(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    parquet_root = Path("data/parquet")
    p = parquet_root / "binance" / "BTCUSDT" / DataType.KLINE_1M.value / "2024" / "01.parquet"
    if not p.exists():
        pytest.skip(f"requires Phase 3 data at {p}")

    profile = StrategyProfile(
        name="smoke-buyhold", version=1, is_active=False, parameters={}
    )
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    from app.models.backtest_run import BacktestRun
    import hashlib, json
    h = hashlib.sha256(json.dumps({}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    run = BacktestRun(
        profile_id=profile.id,
        profile_version=1,
        profile_hash=h,
        strategy_name="buy_and_hold",
        venue="binance",
        symbols=["BTCUSDT"],
        start_ts=datetime(2024, 1, 1, tzinfo=UTC),
        end_ts=datetime(2024, 1, 31, 23, 59, tzinfo=UTC),
        status="pending",
    )
    db_session.add(run)
    await db_session.flush()
    await db_session.commit()

    curves = tmp_path / "curves"
    service = BacktestService(
        session=db_session, parquet_root=parquet_root, backtest_curves_root=curves,
    )
    await service.execute(run.id)
    await db_session.refresh(run)
    assert run.status == "complete"
    assert run.num_trades is not None and run.num_trades >= 1
    assert run.equity_curve_path is not None
```

- [ ] **Step 2: Append README section** — add after the "Data pipeline (Phase 3)" block:

````markdown
## Backtester (Phase 4)

Run a backtest by creating a `BacktestRun` row + dispatching the worker. End-to-end:

### Via API

```bash
# Create a pending run; profile_hash + profile_version locked at row creation
curl -X POST http://localhost:8000/api/v1/backtests \
  -H "Content-Type: application/json" \
  -d '{
    "profile_id": "<uuid>",
    "strategy_name": "buy_and_hold",
    "start_ts": "2024-01-01T00:00:00Z",
    "end_ts":   "2024-01-31T23:59:00Z",
    "venue":    "binance",
    "symbols": ["BTCUSDT"]
  }'

# Then fire the worker with the returned run_id
docker compose --profile jobs run --rm -e BACKTEST_ID=<run_id> worker-run-backtest
```

### Via just

```bash
just backtest <run_id>
```

### Polling

```bash
curl http://localhost:8000/api/v1/backtests/<run_id>
```

Result includes `total_return`, `sharpe`, `max_drawdown`, `num_trades`, and `equity_curve_path` (a Parquet file under `data/backtest_runs/`).

### Available strategies

- `buy_and_hold` — engine validator: opens one long spot position on the first tick, holds.
- `funding_arb_skeleton` — engine validator: opens a delta-neutral (long spot + short perp) pair on first tick, holds. Exercises funding accounting.

Real strategies (Strategy A funding arb with calibration, Strategy B factor portfolio) ship in Phase 6+.
````

- [ ] **Step 3: Full sweep**

```bash
just test && just typecheck && just lint
```
Expected: all green; ~89 tests pass (slow test deselected).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/test_backtest_smoke.py README.md
git commit -m "test+docs: backtest smoke test (slow) + README backtester section"
```

---

### Task 23: PR via /pr-summary

- [ ] **Step 1: Confirm gates green**

```bash
just test && just typecheck && just lint
```

- [ ] **Step 2: Invoke /pr-summary**

The parent agent invokes `/pr-summary` to:
- Analyse the diff against `main`
- Compute version bump (MINOR — every commit is `feat:` or `chore:`, no breaking changes; 0.3.0 → 0.4.0)
- Generate CHANGELOG entry
- Bump version via `./scripts/bump-version.sh minor`
- Predict next PR number, backfill the spec at `docs/superpowers/specs/2026-05-24-cryptobot-backtester-design.md` Revision history
- Commit `chore: bump version to v0.4.0`
- Annotated-tag `v0.4.0`
- Push `--follow-tags`
- Open the PR

Do NOT run `gh pr create` directly. /pr-summary owns the release pipeline.

---

## Plan self-review

- **Spec coverage**: Architecture (Tasks 13, 14), persistence split (Tasks 4, 5, 16), audit trail (Task 19+20), profile registry additions (Tasks 1, 12), fill model (Task 7), funding (Task 8), metrics (Task 9), API (Task 19), worker (Tasks 17, 18), strategies (Tasks 11, 12), docker-compose (Task 18), smoke + README (Task 22), AST lint extension (Task 21). All spec sections covered.
- **Type consistency**: `ProfileParams(values=...)` constructor is used consistently across all task tests; `from_profile_parameters` factory added in Task 16. `BacktestResult` (engine internal) vs `BacktestRunResult` (runner wrapper) — different names, different scopes, intentional. `Strategy` Protocol is the same in `strategies/base.py` and used by `Engine.__init__` and `StrategyRegistry`.
- **Constraint #1 enforcement**: All numeric literals in `backtest/*.py` and `backtest/strategies/*.py` either come from the registry (slippage, fees, initial cash, minutes per year, hedge fraction) or are documented module-level unit-of-measure constants (`_BPS_DIVISOR`). Task 21 adds AST lint coverage.
- **Constraint #4 enforcement**: `profile_hash` set in API endpoint (Task 19) at row creation, before the worker runs. Audit-trail test (Task 20) proves mutating the profile after the run leaves the hash untouched.
- **TDD discipline**: every task is RED → GREEN → COMMIT. Engine tests use hand-crafted Parquet fixtures (Task 13) for determinism.
- **Frequent commits**: 22 implementation commits + 1 PR commit, mean ~50 LOC each.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-24-cryptobot-backtester.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec compliance → code quality), fast iteration.

**2. Inline Execution** — execute tasks in this session, batch with checkpoints.

Which approach?
