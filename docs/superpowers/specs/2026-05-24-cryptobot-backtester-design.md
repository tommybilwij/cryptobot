# Cryptobot Phase 4 — Backtester Design Spec

**Date**: 2026-05-24
**Status**: approved (brainstorming)
**Phase**: 4 of the cryptobot build
**Blocks**: Phase 5 (exchange adapters), Phase 6 (Strategy A funding arb), Phase 14+ (factor portfolio backtests, IC discipline)
**Revision history**: v1 — initial. PR #<fill-in-after-merge>.

## Goal

A bar-by-bar backtest engine that consumes historical Parquet data via `DuckDBQuery`, executes a pure `Strategy.evaluate(state, params) → list[Order]` function with the **same `ProfileParams`** the live engine will load, and produces a persisted `BacktestRun` row + Parquet equity curve. Engine is delivered async via a worker job, fronted by an HTTP API, audited per-row with `profile_hash`.

## Non-goals

- Walk-forward / cross-validation windowing → Phase 14.
- Real Strategy A logic (entry/exit, calibration, capacity caps) → Phase 6. Phase 4 ships two **engine validators** only: `BuyAndHoldStrategy` and `FundingArbSkeleton`.
- Meta-allocator multi-strategy backtest → Phase 18.
- L2 / order-book simulation. We only have OHLCV + funding + OI from public archives.
- Strategy Lab UI / equity-curve plotting → Phase 19 frontend phases.
- Live-fill calibration of `slippage_bps` defaults → Phase 9+ once we have testnet/dry-run fills.
- Multi-venue cash ledger reconciliation. Phase 4 assumes a single USDC pool across venues; revisit at Phase 8 when Strategy A scales.

## Architecture

Event-driven engine in `backend/app/backtest/`. Walks the time grid from `start_ts` to `end_ts` at a profile-configurable cadence (`backtest.bar_interval_s`, default 60). At each tick:

1. Build `MarketSnapshot` from DuckDB (per (venue, symbol, product) bar)
2. Apply per-venue funding payments to current positions (`FundingLedger`)
3. Hand `MarketState = (snapshot, positions, cash)` to `strategy.evaluate(state, params)`
4. Apply returned `list[Order]` through `FillSimulator` (constant-bps slippage + fees from profile)
5. Update `PositionBook` + cash
6. Mark-to-market → append `(ts, equity, cash, num_open_positions)` to equity curve

Funding payments apply **before** the strategy is invoked so it sees the post-funding balance. Cadence is data-driven from the funding-rate Parquet — Hyperliquid emits 1h rows, Binance perp 8h.

**Same-profile-as-live** (Constraint #2 from project CLAUDE.md): the harness instantiates `ProfileParams` from `profile_id` exactly the way the live worker will. Strategy code is identical. The only diff is the data source — `DuckDBQuery` historical bars vs. future live streams.

**Async via worker** matching the existing `refresh_data` pattern:

```
POST /api/v1/backtests          → 202 + run_id (BacktestRun row inserted, status='pending')
WORKER_JOB=run_backtest BACKTEST_ID=<uuid> python -m app.worker.main
                                  → runs engine, writes Parquet, marks complete
GET /api/v1/backtests/{id}      → status + summary stats + equity_curve_path
```

**Persistence split**:
- **Postgres** (`backtest_runs` table) — ids, profile snapshot (`profile_id` + `profile_version` + `profile_hash`), date range, status, summary stats (`total_return`, `sharpe`, `max_drawdown`, `num_trades`), `error_message`, timestamps.
- **Parquet** at `data/backtest_runs/{run_id}.parquet` — full equity curve. Keeps Postgres lean, plot-time queries fast.

## Components

```
backtest/
  __init__.py
  engine.py           # event loop: walks bars, calls strategy, applies orders, marks-to-market
  state.py            # MarketState, MarketSnapshot dataclasses
  orders.py           # Order, OrderType, Fill dataclasses
  fills.py            # FillSimulator: constant-bps slippage + fees from ProfileParams
  funding.py          # FundingLedger: applies per-venue funding at venue cadence
  positions.py        # PositionBook: tracks open positions across (venue, symbol, product)
  metrics.py          # equity-curve → Sharpe, max_dd, total_return, num_trades
  loader.py           # DuckDBQuery → time-indexed bar generator
  runner.py           # high-level: run_backtest(profile_params, strategy, start, end, venue, symbols)
  strategies/
    __init__.py
    buy_and_hold.py           # BuyAndHoldStrategy validator
    funding_arb_skeleton.py   # FundingArbSkeleton validator (hedge pair + funding)
```

Strategy file structure differs from `backend/app/strategies/` (which holds the *real* live strategies). Backtest validators are deliberately separate so the AST-lint-no-literals rule covers both directories.

## Data shapes

```python
@dataclass(frozen=True)
class Bar:
    ts_ms: int
    venue: str
    symbol: str
    product: Literal["spot", "perp"]
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass(frozen=True)
class MarketSnapshot:
    ts_ms: int
    bars: dict[tuple[str, str, str], Bar]   # (venue, symbol, product) → Bar

@dataclass(frozen=True)
class Position:
    venue: str
    symbol: str
    product: Literal["spot", "perp"]
    qty_base: float        # signed: + long, - short
    avg_entry_px: float

@dataclass(frozen=True)
class MarketState:
    snapshot: MarketSnapshot
    positions: tuple[Position, ...]
    cash_quote: float

@dataclass(frozen=True)
class Order:
    venue: str
    symbol: str
    product: Literal["spot", "perp"]
    side: Literal["buy", "sell"]
    qty_base: float
    order_type: Literal["market", "limit"]
    limit_px: float | None = None

@dataclass(frozen=True)
class Fill:
    ts_ms: int
    order: Order
    fill_px: float
    fee_quote: float

class Strategy(Protocol):
    name: str
    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]: ...
```

`Order` carries venue + product so a single `evaluate()` call can emit atomic hedge pairs (short perp + long spot). Strategies are pure — anything they need to "remember" must live in `state.positions`.

## Database

**New ORM `BacktestRun`** at `backend/app/models/backtest_run.py`:

```python
class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_profiles.id"), nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256 hex
    strategy_name: Mapped[str] = mapped_column(String(80), nullable=False)
    venue: Mapped[str] = mapped_column(String(40), nullable=False)
    symbols: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # pending|running|complete|failed
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    num_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    equity_curve_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

Alembic migration `0003_create_backtest_runs`. Reversible (down = `drop_table`).

## Profile registry additions

New keys under `PROFILE_SCOPED_DEFAULTS`:

```
execution.slippage_bps.binance         float, default  5.0
execution.slippage_bps.bybit           float, default  5.0
execution.slippage_bps.hyperliquid     float, default  8.0
execution.fee_bps.binance.spot         float, default 10.0
execution.fee_bps.binance.perp         float, default  4.0
execution.fee_bps.bybit.perp           float, default  5.5
execution.fee_bps.hyperliquid.perp     float, default  3.5
backtest.initial_cash_quote_usdc       float, default 10000.0
backtest.bar_interval_s                int,   default 60
```

Per Constraint #1 from project CLAUDE.md, **no numeric literals in `backtest/engine.py`, `fills.py`, `funding.py`, `metrics.py`, or any strategy file**. Engine reads everything via `params.get(path)`. The AST lint script's target list gets extended to `backend/app/backtest/{engine,fills,funding,metrics}.py` and `backend/app/backtest/strategies/**` alongside the existing `backend/app/strategies/**`.

## API

**`POST /api/v1/backtests`** — async kickoff. Request:
```json
{
  "profile_id": "uuid",
  "strategy_name": "buy_and_hold",
  "start_ts": "2024-01-01T00:00:00Z",
  "end_ts": "2024-01-31T23:59:00Z",
  "venue": "binance",
  "symbols": ["BTCUSDT"]
}
```
Response: `202 Accepted` with `{ "id": "uuid", "status": "pending" }`.

The endpoint:
1. Validates `profile_id` exists → 422 otherwise.
2. Validates `strategy_name` is in the strategy registry → 422 otherwise.
3. Computes `profile_hash = sha256(canonical_json(profile.parameters))` and stores it alongside `profile_version` (Constraint #4 — audit lock happens at row creation, before the worker runs).
4. Validates the date range has Parquet data via `DuckDBQuery` (cheap path-existence check on partitions) → 422 if no data.
5. Inserts the `BacktestRun` row with `status='pending'`.
6. Returns 202 + `run_id`.

**`GET /api/v1/backtests/{id}`** — poll. Response:
```json
{
  "id": "uuid",
  "profile_id": "uuid",
  "profile_version": 3,
  "profile_hash": "abc123...",
  "strategy_name": "buy_and_hold",
  "venue": "binance",
  "symbols": ["BTCUSDT"],
  "start_ts": "...",
  "end_ts": "...",
  "status": "complete",
  "total_return": 0.0234,
  "sharpe": 1.47,
  "max_drawdown": -0.041,
  "num_trades": 1,
  "equity_curve_path": "data/backtest_runs/<uuid>.parquet",
  "error_message": null,
  "created_at": "...",
  "started_at": "...",
  "completed_at": "..."
}
```
404 on unknown id.

**`GET /api/v1/backtests`** — list, paginated by `created_at desc`, `?limit=50&offset=0`. Optional filters: `?profile_id=...`, `?strategy_name=...`, `?status=...`.

## Worker job

New job `backend/app/worker/jobs/run_backtest.py` registered in `_JOBS` dict in `worker/main.py`:

```python
async def run() -> None:
    run_id = os.environ.get("BACKTEST_ID")
    if not run_id:
        raise KeyError("BACKTEST_ID env var required")
    # Open DB session, load BacktestRun, apply profile, run engine, persist
```

`run_with(session, run_id)` is the testable inner function (matches the `refresh_data.run_with` pattern from Phase 3).

The job:
1. Loads `BacktestRun` by id.
2. Marks `status='running'`, writes `started_at`, commits.
3. Loads the profile + applies it → `ProfileParams`.
4. Resolves strategy by name → `Strategy` instance.
5. Calls `runner.run_backtest(profile_params, strategy, start, end, venue, symbols)`.
6. On success: writes equity-curve Parquet to `data/backtest_runs/{run_id}.parquet`, fills in summary stats, marks `status='complete'`, writes `completed_at`.
7. On exception: marks `status='failed'`, writes `error_message`, writes `completed_at`, re-raises so the worker exits non-zero.

## docker-compose

New service `worker-run-backtest` under `profiles: ["jobs"]`, same shape as `worker-refresh-data`:

```yaml
worker-run-backtest:
  build: { context: ./backend, dockerfile: Dockerfile }
  container_name: cryptobot-worker-run-backtest
  restart: "no"
  command: uv run python -m app.worker.main
  environment:
    WORKER_JOB: run_backtest
    BACKTEST_ID: ${BACKTEST_ID:?BACKTEST_ID is required}
    DATABASE_URL: postgresql+asyncpg://cryptobot:${POSTGRES_PASSWORD:-devpass}@postgres:5432/cryptobot
    DATABASE_URL_SYNC: postgresql+psycopg://cryptobot:${POSTGRES_PASSWORD:-devpass}@postgres:5432/cryptobot
  depends_on:
    postgres: { condition: service_healthy }
  profiles: ["jobs"]
```

`just backtest` recipe runs the worker locally:

```just
backtest BACKTEST_ID:
    cd backend && WORKER_JOB=run_backtest BACKTEST_ID={{BACKTEST_ID}} uv run python -m app.worker.main
```

## Fill model

`FillSimulator`:
- **Market order, buy**: fill at `bar.close * (1 + slippage_bps / 10_000)`
- **Market order, sell**: fill at `bar.close * (1 - slippage_bps / 10_000)`
- **Fee**: `fee_bps[venue][product] / 10_000 * fill_notional`, debited from cash
- **Limit order**: filled at `limit_px` if `bar.low <= limit_px <= bar.high` (touched in the bar), else not filled (carried to next bar — or dropped at end-of-window; design decision: **dropped**, no order book persistence in Phase 4)
- **Insufficient cash**: order rejected, logged as event, engine continues

Slippage + fee bps come from `params.get("execution.slippage_bps.<venue>")` and `params.get("execution.fee_bps.<venue>.<product>")` — no literals.

## Funding ledger

`FundingLedger` reads the funding-rate Parquet from `data/parquet/{venue}/{symbol}/funding_rate/{year}/{month}.parquet`. For each perp position, at each funding event timestamp covered by the backtest window:

```
position_notional = abs(qty_base) * last_close_px
funding_payment   = -sign(qty_base) * position_notional * realized_funding_rate
cash             += funding_payment
```

Convention: positive funding → longs pay shorts. A short perp with `qty_base < 0` collects when funding is positive. A long perp with `qty_base > 0` pays.

Cadence is data-driven: whatever timestamps exist in the funding Parquet are when the event fires. No hardcoded interval.

## Metrics

`metrics.py`:
- **`total_return`** = `(equity[-1] - initial_cash) / initial_cash`
- **`sharpe`** = annualised Sharpe over minute-bar returns, using **525,600 minutes/year** (24/7 crypto). Risk-free rate = 0 (matches HLP benchmark convention).
- **`max_drawdown`** = `max(peak - trough) / peak` over the equity curve, expressed as a negative float (e.g. `-0.041` for 4.1% drawdown)
- **`num_trades`** = count of filled orders (not count of bars). Reset to 0 on a fresh run.

Sharpe annualisation factor is registry-driven: `metrics.minutes_per_year` default 525_600, so jurisdictions with different conventions (or different bar cadences) can override.

## Testing strategy

~25 new tests under `backend/tests/backtest/` + extensions to `tests/test_worker_jobs.py` + `tests/api/test_backtests.py`.

**Unit (pure logic, fast)**:
- `test_orders.py` — Order/OrderType validation, signed qty semantics
- `test_positions.py` — PositionBook.apply(fills) math: open, add, partial close, full close, sign flip
- `test_fills.py` — FillSimulator: bps math, fee math, slippage direction, insufficient-cash rejection
- `test_funding.py` — FundingLedger: long pays positive funding to short, per-venue cadence, no-perp = no-op, multi-position summation
- `test_metrics.py` — Sharpe (24/7 annualisation), max_dd, total_return on hand-crafted equity curves

**Integration (engine end-to-end, hand-crafted Parquet fixtures)**:
- `test_engine_buyhold.py` — BuyAndHoldStrategy over 3-bar fixture: 1 trade at start, equity matches hand-computed at each bar
- `test_engine_funding_arb_skeleton.py` — FundingArbSkeleton over hand-crafted fixture with one mid-window funding event: equity matches `position_notional * funding_rate` exactly
- `test_engine_no_data_raises.py` — empty window or missing Parquet → `BacktestDataError`
- `test_engine_zero_orders_is_noop.py` — empty orders per tick → flat equity at initial cash

**Worker + API**:
- `tests/test_worker_jobs.py` (append) — `WORKER_JOB=run_backtest BACKTEST_ID=<uuid>` dispatches; missing BACKTEST_ID → KeyError
- `tests/api/test_backtests.py` — POST creates pending row; GET returns row; 404 on missing; 422 on bad profile_id or strategy_name; 422 when date range has no data

**Audit (Constraint #4)**:
- `test_audit_trail.py` — after a run, `BacktestRun.profile_hash == sha256(canonical_json(profile.parameters at run time))`; mutating profile params AFTER the run leaves the hash unchanged

**AST lint extension**:
- `scripts/lint_no_literals_in_strategies.py` target list adds `backend/app/backtest/{engine,fills,funding,metrics}.py` and `backend/app/backtest/strategies/**`

## Edge cases

- Missing data in [start, end] → `BacktestDataError` with the gap range (worker marks status='failed', writes the error to `error_message`)
- Strategy emits Order on a symbol with no Parquet data → `BacktestDataError` (same handling)
- Cash goes negative after a fill → fill rejected; engine logs `insufficient_cash` event and continues (no row-level failure)
- Funding payment on a closed position (`qty_base == 0`) → no-op (PositionBook returns 0 notional)
- Profile missing a required key → ProfileParams default fallback (Constraint #3); engine never sees a missing key
- Strategy raises during `evaluate()` → engine catches, marks status='failed', writes error_message (worker doesn't crash mid-run; cleanup is atomic)
- Backtest window narrower than one funding interval → no funding events; equity = mark-to-market only

## Definition of done (gate to Phase 5)

- ~89 tests total pass (64 existing + ~25 new). mypy --strict + ruff + AST lint clean.
- `POST /api/v1/backtests` + `GET /api/v1/backtests/{id}` work end-to-end (manual smoke against BuyAndHoldStrategy over the BTCUSDT Parquet data from Phase 3).
- `BuyAndHoldStrategy` over 30 days of BTCUSDT data: equity curve matches hand-spot-check at start, mid, end.
- `FundingArbSkeleton` over a synthetic funding fixture: total funding payments collected match `Σ (notional * funding_rate)` exactly.
- Alembic migration `0003_create_backtest_runs` applies cleanly + reverses cleanly.
- `BacktestRun.profile_hash` set on every row.
- `docker compose --profile jobs config --quiet` exits 0 with the new service.
- No numeric literals in `backtest/engine.py`, `fills.py`, `funding.py`, `metrics.py`, or any strategy file (AST lint enforced).

## Open questions

None at design time. Worker concurrency (can two backtests run in parallel?) defers to runtime: docker-compose `worker-run-backtest` is single-shot, so concurrency is opt-in by spawning multiple containers with different `BACKTEST_ID`s. Phase 5+ may add an orchestrator if needed.

## References

- `docs/superpowers/research/cryptobot-strategy-architecture.md` — strategy architecture (Constraints #1–5)
- `docs/superpowers/plans/2026-05-24-cryptobot-data-pipeline.md` — Phase 3 data pipeline (DuckDBQuery, ParquetStore)
- `backend/app/strategies/` — live Strategy Protocol from Phase 1+2 (will be made concrete in Phase 6)
- `backend/app/services/profile_service.py` + `backend/app/profile/params.py` — profile resolution + ProfileParams accessor pattern
- `../stockbot/backend/app/services/` — reference patterns for fee/slippage modelling and backtest audit
