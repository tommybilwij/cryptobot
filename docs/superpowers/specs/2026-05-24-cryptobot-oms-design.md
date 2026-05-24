# Cryptobot Phase 5 — Exchange Adapters + OMS + Decision Audit Design Spec

**Date**: 2026-05-24
**Status**: approved (autonomous mode — user delegated design defaults)
**Phase**: 5 of the cryptobot build
**Blocks**: Phase 6 (Strategy A funding arb), Phase 7 (testnet integration), Phase 8 (dry-run), Phase 9 (live $500)
**Revision history**: v1 — initial. PR #7.

## Goal

Land the **exchange-facing infrastructure** that Strategy A (Phase 6) and the live runner (Phase 7+) will need: a uniform `Exchange` Protocol with REST adapter implementations for Binance, Bybit, and Hyperliquid; an OMS service that takes `list[Order]` from `Strategy.evaluate()` and dispatches with reconciliation + kill switch; and a `DecisionAuditEntry` log that captures every order-producing decision (Constraint #4) plus periodic state snapshots.

## Non-goals

- **Live testnet integration** → Phase 7. Phase 5 adapters use `httpx.MockTransport` for tests. No real network calls.
- **WebSocket streams** → Phase 7+. REST polling is good enough for funding arb (1m cadence).
- **Drawdown brake, Kelly sizer, vol targeting, Bayesian risk** → Phase 8 risk machinery. Phase 5 has ONLY the binary kill switch + hedge-drift halt.
- **Sub-accounts / per-strategy API keys** → Phase 9+ (when capital and strategies scale). Phase 5 uses a single API key per venue, read from env.
- **Strategy A logic** → Phase 6. Phase 5 ships a `live_runner` *stub* that the runner phase will fill in.
- **Order book / L2 / WebSocket fills** → Phase 7+.
- **Async / limit-order machinery beyond scaffolding** → Strategy A is market-only; we scaffold async polling but only test the sync path.

## Architecture

Three layered concerns, one PR:

### 1. Exchange adapter layer (`backend/app/exchanges/`)

Common `Exchange` Protocol satisfied by:
- `paper.py` — in-memory adapter (unit tests + Phase 8 dry-run)
- `binance.py` — Binance REST (spot + USDS-margined perp)
- `bybit.py` — Bybit REST (USDT perp)
- `hyperliquid.py` — Hyperliquid REST (perp, EVM-signed)

Each adapter owns one venue's quirks: URL paths, auth signing, response shape, error mapping. The OMS only sees the Protocol.

All HTTP traffic goes through `httpx.AsyncClient` + a shared `RetryingFetcher` (already exists from Phase 3 for the data pipeline — extend, don't duplicate).

### 2. OMS service (`backend/app/oms/`)

```
oms/
  service.py            # OMS.dispatch(orders, state) → list[Fill]
  kill_switch.py        # KillSwitch.is_active() → bool (reads profile registry)
  reconciler.py         # PositionReconciler: book vs exchange drift, spot vs perp drift
  ledger.py             # MultiVenueCashLedger: USDC pool across venues
  exceptions.py         # KillSwitchActive, HedgeDriftHalt, ReconciliationDriftHalt
```

`OMS.dispatch(orders, state)`:
1. Check kill switch → raise `KillSwitchActive` if flipped
2. For each `Order`, look up the right adapter by `order.venue`
3. Call `adapter.place_order(order)` → `OrderReceipt`
4. Poll `adapter.fetch_order(receipt.order_id)` until filled (or timeout from registry)
5. Re-fetch positions from each touched venue
6. Call `PositionReconciler.check(expected_book, exchange_positions)` → raise `ReconciliationDriftHalt` if > registry threshold
7. Call `PositionReconciler.hedge_consistency(positions)` → raise `HedgeDriftHalt` if > registry threshold
8. Build `Fill` records, write `DecisionAuditEntry`, return fills

The OMS is **synchronous per dispatch** — Strategy A's hedge pair (long spot + short perp) is two orders, OMS sends both, waits for both, reconciles, returns. Atomic from the strategy's POV.

### 3. Decision audit (`backend/app/services/decision_audit.py`)

ORM table `decision_audit_entries`:
- `id`, `ts`, `strategy_name`, `profile_id`, `profile_version`, `profile_hash`
- `decision_type` enum: `order` (orders emitted), `snapshot` (hourly heartbeat, no orders)
- `input_state` JSONB — positions + cash + key marks at decision time
- `orders` JSONB — what the strategy returned
- `fills` JSONB — what the OMS confirmed
- `reconciliation_status` enum: `ok` | `halted_hedge_drift` | `halted_book_drift` | `kill_switch`
- `reason` text — why halted, if applicable
- `created_at`

Service:
- `DecisionAuditService.log_decision(...)` called by OMS at end of every dispatch
- `DecisionAuditService.log_snapshot(...)` called by the live runner once per hour (no orders, just state)
- `DecisionAuditService.get_recent(limit, filters)` for the API

API:
- `GET /api/v1/decision-audit/recent?strategy_name=&limit=&decision_type=`
- `GET /api/v1/oms/status` — kill switch state, last-dispatch timestamp, recent reconciliation events
- `POST /api/v1/oms/kill` — flip the kill switch flag on the active profile (writes a new profile version)

## Components

### Exchange Protocol (`backend/app/exchanges/base.py`)

```python
@dataclass(frozen=True)
class Balance:
    venue: str
    quote_currency: str   # "USDC" / "USDT"
    free: float
    locked: float

@dataclass(frozen=True)
class ExchangePosition:
    venue: str
    symbol: str
    product: Product       # "spot" | "perp"
    qty_base: float        # signed
    avg_entry_px: float
    mark_px: float
    unrealized_pnl_quote: float

@dataclass(frozen=True)
class OrderReceipt:
    order_id: str
    venue: str
    symbol: str
    submitted_ts_ms: int

@dataclass(frozen=True)
class OrderStatus:
    order_id: str
    status: Literal["pending", "filled", "partially_filled", "cancelled", "rejected"]
    fill_px: float | None
    filled_qty_base: float
    fee_quote: float
    raw: dict[str, Any]    # exchange-native body for debugging

class Exchange(Protocol):
    name: str

    async def fetch_balance(self, quote_currency: str) -> Balance: ...
    async def fetch_positions(self) -> tuple[ExchangePosition, ...]: ...
    async def place_order(self, order: Order) -> OrderReceipt: ...
    async def fetch_order(self, order_id: str) -> OrderStatus: ...
    async def cancel_order(self, order_id: str) -> None: ...
    async def fetch_mark_price(self, symbol: str, product: Product) -> float: ...
```

`Order` is the same dataclass from `backend/app/backtest/orders.py` (Phase 4). The OMS bridges backtest-shape orders to live execution.

### Paper adapter (`backend/app/exchanges/paper.py`)

In-memory state machine. Used by:
1. Unit tests (deterministic fills, no HTTP)
2. Phase 8 dry-run mode (live data, paper fills)

Implements `Exchange` Protocol with a configurable `slippage_bps` + `fee_bps` per venue (read from profile registry — same keys Phase 4 backtest uses, so paper trading = backtest with live data).

### REST adapters (`backend/app/exchanges/{binance,bybit,hyperliquid}.py`)

Each one:
- Constructor takes `RetryingFetcher` + `api_key`/`api_secret` + `base_url`
- All endpoints use the existing `RetryingFetcher` from Phase 3 (extend it if it doesn't support POST — currently GET-only)
- Auth signing per-venue:
  - Binance: HMAC SHA256 over `query_string + body`, header `X-MBX-APIKEY`
  - Bybit: HMAC SHA256 over `timestamp + api_key + recv_window + body`, header `X-BAPI-SIGN`
  - Hyperliquid: EIP-712 typed-data sign over the order payload using the user's EVM private key
- Response shapes normalised to the canonical dataclasses (Balance, OrderReceipt, OrderStatus, ExchangePosition)
- Errors mapped to a shared `ExchangeError` hierarchy: `RateLimited`, `Rejected`, `Timeout`, `AuthFailed`

Phase 5 tests use `httpx.MockTransport` with hand-crafted JSON fixtures matching each venue's docs. Real network calls are Phase 7.

### Extended `RetryingFetcher`

Phase 3's `RetryingFetcher` is GET-only. Extend to support:
- `get_json(url, params, headers) → dict` (was `get_bytes`)
- `post_json(url, body, headers) → dict`

Keep the existing `get_bytes` for the Parquet downloaders.

### OMS dispatch (`backend/app/oms/service.py`)

```python
@dataclass
class DispatchResult:
    fills: list[Fill]
    audit_entry_id: uuid.UUID
    reconciliation_status: str   # "ok" | "halted_hedge_drift" | "halted_book_drift"

class OMS:
    def __init__(
        self,
        *,
        exchanges: dict[str, Exchange],
        audit_service: DecisionAuditService,
        params: ProfileParams,
        kill_switch: KillSwitch,
        reconciler: PositionReconciler,
    ) -> None: ...

    async def dispatch(
        self,
        *,
        orders: list[Order],
        state: MarketState,
        strategy_name: str,
        profile_id: UUID,
        profile_version: int,
        profile_hash: str,
    ) -> DispatchResult: ...
```

The OMS calls `audit_service.log_decision(...)` exactly once per dispatch, with `decision_type="order"`. The hourly snapshot call (`log_snapshot`) is invoked by the (future) live runner, not by the OMS.

### Position reconciler

Two checks per dispatch:

1. **Book vs exchange drift** (`oms.reconcile_drift_halt_pct`, default 0.02 = 2%):
   For each (venue, symbol, product), compare our `PositionBook` qty with `exchange.fetch_positions()` qty. If `abs(book_qty - venue_qty) / max(abs(book_qty), 1e-9) > threshold`, raise `ReconciliationDriftHalt`. Our book is wrong — manual intervention required.

2. **Hedge consistency** (`oms.hedge_drift_halt_pct`, default 0.05 = 5%):
   For each (symbol) with both spot and perp positions, the qty magnitudes should match (delta-neutral). If `abs(abs(spot_qty) - abs(perp_qty)) / max(abs(spot_qty), 1e-9) > threshold`, raise `HedgeDriftHalt`. The hedge slipped; strategy should be halted until the gap closes.

Both are halt-class errors. The strategy that triggered them must be paused (kill switch flipped on its scope).

### Kill switch

Profile registry key: `oms.kill_switch_active: bool = False`.

`KillSwitch.is_active()` reads via `params.get("oms.kill_switch_active")`. Strategies that flip it create a new profile version (via the existing `POST /api/v1/strategy-profiles/{id}/apply` mechanism) — preserves audit trail.

`POST /api/v1/oms/kill` clones the active profile, sets the flag to true, applies the clone. Reversible via the same UI mechanism in Phase 19+ frontend.

### Multi-venue cash ledger

The OMS tracks a single `USDC` pool across venues. Each `Fill` debits/credits the appropriate venue's recorded balance, and the ledger sums them. Used by:
- Position reconciler for "do we have enough cash to send this order"
- Decision audit for `input_state.cash_quote`
- Strategy A capacity check (Phase 6)

Phase 5 only models USDC. USDT/AUD diversification is Phase 9+.

## Database

**New ORM `DecisionAuditEntry`** at `backend/app/models/decision_audit.py`:

```python
class DecisionAuditEntry(Base):
    __tablename__ = "decision_audit_entries"

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True, default=uuid4)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(80), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(UUID, ForeignKey("strategy_profiles.id"), nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(20), nullable=False)   # "order" | "snapshot"
    input_state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    orders: Mapped[list] = mapped_column(JSONB, nullable=False)
    fills: Mapped[list] = mapped_column(JSONB, nullable=False)
    reconciliation_status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

Indexes:
- `(strategy_name, ts DESC)` — recent decisions per strategy
- `(profile_hash, ts DESC)` — replay-by-profile

Alembic migration `0004_create_decision_audit_entries`.

## Profile registry additions

All numeric / string / bool. Added to `PROFILE_SCOPED_DEFAULTS`:

```
oms.kill_switch_active                    bool  default False     (in _STRING_ or new _BOOL_ registry? Use _DICT_ if needed.)
oms.hedge_drift_halt_pct                  float default 0.05
oms.reconcile_drift_halt_pct              float default 0.02
oms.fill_poll_interval_s                  float default 1.0
oms.max_fill_wait_s                       float default 30.0
oms.audit_snapshot_interval_s             int   default 3600
exchanges.binance.use_testnet             bool  default True
exchanges.bybit.use_testnet               bool  default True
exchanges.hyperliquid.use_testnet         bool  default True
exchanges.binance.timeout_s               float default 10.0
exchanges.bybit.timeout_s                 float default 10.0
exchanges.hyperliquid.timeout_s           float default 10.0
```

**Bool registry**: Phase 1+2's three-typed registry has `PROFILE_SCOPED_DEFAULTS` (numeric), `PROFILE_SCOPED_STRING_DEFAULTS`, `PROFILE_SCOPED_DICT_DEFAULTS`. There's no `_BOOL_` registry yet. Phase 5 adds a fourth: `PROFILE_SCOPED_BOOL_DEFAULTS`, with the same accessor pattern via `params.get()`. Existing `ProfileParams.get()` walks all four.

Per Constraint #1, no numeric/bool literals in `backend/app/oms/**`, `backend/app/exchanges/**`. AST lint extension covers these in Task 21-equivalent.

## API

**`POST /api/v1/oms/kill`** — flips the kill switch on the active profile.
Request: empty body (or `{ "reason": "..." }` for the audit log).
Response: `{ "active_profile_id": "...", "kill_switch_active": true, "new_version": N }`.

**`GET /api/v1/oms/status`** — current state.
Response:
```json
{
  "kill_switch_active": false,
  "active_profile_id": "...",
  "active_profile_version": 3,
  "last_dispatch_ts": "...",
  "last_reconciliation_status": "ok",
  "venues": [
    {"name": "binance", "configured": true, "use_testnet": true},
    ...
  ]
}
```

**`GET /api/v1/decision-audit/recent?strategy_name=&limit=50&decision_type=`** — query audit entries.
Response: `list[DecisionAuditResponse]` (Pydantic model mirroring the ORM fields).

## API key configuration

API keys read from env (NOT profile registry — secrets don't go in DB):
- `BINANCE_API_KEY`, `BINANCE_API_SECRET`
- `BYBIT_API_KEY`, `BYBIT_API_SECRET`
- `HYPERLIQUID_WALLET_PRIVATE_KEY` (EVM private key)

`backend/app/config.py` (`Settings` pydantic-settings instance) extended to expose these. Adapters read from `settings`. Tests use mocked HTTP so no real keys needed.

Phase 0 ops checklist (already shipped) covers user-side key creation: withdrawals disabled, IP whitelist, separate key per strategy in Phase 9+.

## Testing strategy

~25 new tests under `backend/tests/{exchanges, oms, services, api}/`:

**Adapter unit tests** (per-venue, MockTransport):
- `tests/exchanges/test_paper.py` — paper adapter state machine (place → fill → balance updates)
- `tests/exchanges/test_binance.py` — auth signing, place_order body shape, fetch_balance parses response, error mapping
- `tests/exchanges/test_bybit.py` — same shape, Bybit-specific
- `tests/exchanges/test_hyperliquid.py` — EIP-712 signing fixture, place_order body shape

**OMS tests**:
- `tests/oms/test_dispatch.py` — happy path: 2-leg hedge pair dispatches against 2 paper adapters, fills returned, audit logged
- `tests/oms/test_kill_switch.py` — kill switch flag halts dispatch
- `tests/oms/test_reconciler.py` — book vs exchange drift detection; hedge consistency drift detection
- `tests/oms/test_ledger.py` — multi-venue cash accounting

**Service tests**:
- `tests/services/test_decision_audit.py` — log_decision, log_snapshot, get_recent

**API tests**:
- `tests/api/test_oms.py` — status endpoint, kill endpoint flips flag
- `tests/api/test_decision_audit.py` — recent endpoint returns entries with filters

**Audit (Constraint #4)**:
- `tests/oms/test_audit_trail.py` — every dispatch writes exactly one DecisionAuditEntry with profile_hash matching the active profile at dispatch time. Mutating profile after doesn't change the row.

**AST lint extension**:
- `scripts/lint_no_literals_in_strategies.py` adds `backend/app/oms/{service,reconciler,ledger,kill_switch}.py` and `backend/app/exchanges/{paper,binance,bybit,hyperliquid}.py` to scan list. The same module-level `_NAME = literal` carveout from Phase 4 applies.

## Edge cases

- **Order placement timeout** → adapter returns `OrderReceipt`, OMS polls via `fetch_order` up to `oms.max_fill_wait_s`. On timeout, calls `adapter.cancel_order` and records partial fill (if any) in the audit. Strategy sees an empty `fills` list and a "timeout" reconciliation status.
- **Partial fill** → `OrderStatus.status = "partially_filled"`. OMS records the partial fill, no halt. Reconciliation will catch any drift > threshold next dispatch.
- **Exchange returns 429** → `RetryingFetcher` handles backoff (already in Phase 3). Hits `max_retries` → raises `RateLimited`. OMS records as failed dispatch, no halt (transient).
- **Exchange returns 5xx** → same retry path; on max retries, OMS marks dispatch failed.
- **Auth failure (401/403)** → raises `AuthFailed`. OMS halts via kill switch (this is critical — wrong keys mean we don't know what's happening on the venue). Manual unlock required.
- **Kill switch already flipped** when dispatch is called → raises `KillSwitchActive` immediately, no orders sent, audit entry written with `decision_type="order"` and `reconciliation_status="kill_switch"`.
- **Profile lacks an exchange config** → adapter returns "unconfigured", dispatch raises `UnconfiguredVenue` if the strategy emits an order for that venue.
- **Position drift detected but it's our first dispatch** → on cold-start, expected book is empty; reconciler should skip the drift check if `abs(book_qty) < 1e-9`. Only check after we've written something.

## Definition of done (gate to Phase 6)

- ~135 tests total (Phase 4 final was 122) — mypy --strict + ruff + AST lint clean
- All three REST adapter unit tests pass against MockTransport with hand-crafted JSON fixtures matching each venue's docs
- OMS happy-path test: 2-leg hedge pair dispatch succeeds end-to-end with paper adapter; one `DecisionAuditEntry` written
- Kill switch test: flag set → `dispatch` raises `KillSwitchActive`, audit entry logged with `reconciliation_status="kill_switch"`
- Hedge drift test: synthetic positions with 6% drift → `HedgeDriftHalt` raised on next dispatch
- Book drift test: synthetic mismatch with 3% drift → `ReconciliationDriftHalt` raised
- `POST /api/v1/oms/kill` end-to-end via async_client: flips flag, creates new profile version
- Alembic migration `0004_create_decision_audit_entries` applies cleanly + reverses cleanly
- No numeric / boolean literals in `backend/app/oms/**` or `backend/app/exchanges/**` (AST lint enforced)
- New `PROFILE_SCOPED_BOOL_DEFAULTS` registry working alongside the existing three

## Out of scope (deferred)

- Real testnet API calls → Phase 7
- WebSocket fills → Phase 7
- Sub-account per strategy → Phase 9+
- Cross-venue arbitrage routing → never (we don't run that strategy)
- USDT / AUD ledger diversification → Phase 9+
- Drawdown brake / Kelly sizer / vol targeting → Phase 8 risk machinery
- Strategy A code → Phase 6

## References

- `docs/superpowers/research/cryptobot-strategy-architecture.md` — exchange selection, fee tables, API key hygiene rules
- `docs/superpowers/research/cryptobot-phase-0-ops-checklist.md` — API key creation runbook
- `docs/superpowers/specs/2026-05-24-cryptobot-backtester-design.md` — backtest engine; OMS bridges its `Order` dataclass to live execution
- `backend/app/backtest/orders.py` — `Order` + `Fill` dataclasses reused live
- `backend/app/backtest/state.py` — `MarketState` reused as input to `OMS.dispatch`
- `backend/app/market_data/_http.py` — `RetryingFetcher` to be extended for POST + JSON
- `backend/app/profile/{defaults, params}.py` — registry to add `_BOOL_DEFAULTS` dict
- `../stockbot/backend/app/services/decision_audit.py` — pattern reference for the audit ORM and service
- `../stockbot/backend/app/services/kill_switch.py` — pattern reference for the kill switch
