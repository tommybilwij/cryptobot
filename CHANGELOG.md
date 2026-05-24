# Changelog

### v0.5.0 (2026-05-24)

#### Features
- Exchange adapter layer: uniform `Exchange` Protocol satisfied by `PaperExchange` (in-memory deterministic fills) + 3 REST adapters: `BinanceExchange` (HMAC), `BybitExchange` V5 (HMAC), `HyperliquidExchange` (EVM signing via eth_account)
- Order Management System: `OMS.dispatch(orders, state, ...) → DispatchResult` with kill switch + venue validation + sequential order placement + fill polling + audit logging
- Halt-class drift detection: `PositionReconciler` checks book vs exchange (default 2% threshold) + spot/perp hedge consistency (default 5%); halt classes `HedgeDriftHalt`, `ReconciliationDriftHalt`, `KillSwitchActive`, `UnconfiguredVenueError`
- Decision audit: `DecisionAuditEntry` ORM + service (`log_decision`, `log_snapshot`, `get_recent`); audit-locked `profile_hash` (sha256 over canonical-JSON profile config) at dispatch time (Constraint #4)
- Profile registry fourth dict `PROFILE_SCOPED_BOOL_DEFAULTS` alongside numeric/string/dict; `ProfileParams.get()` walks all four
- New profile keys: `oms.kill_switch_active`, `oms.hedge_drift_halt_pct`, `oms.reconcile_drift_halt_pct`, `oms.fill_poll_interval_s`, `oms.max_fill_wait_s`, `oms.audit_snapshot_interval_s`, `exchanges.{venue}.use_testnet`, `exchanges.{venue}.timeout_s`
- Settings exchange API key fields (env-only): `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `HYPERLIQUID_WALLET_PRIVATE_KEY`
- `RetryingFetcher` extended with `get_json` + `post_json` (alongside existing `get_bytes`)
- `MultiVenueCashLedger` tracks USDC as a single logical pool across venues
- Async API: `POST /api/v1/oms/kill` (flips kill switch on active profile + bumps version), `GET /api/v1/oms/status`, `GET /api/v1/decision-audit/recent` with filters
- Alembic migration 0004: `decision_audit_entries` table with composite indexes on (strategy_name, ts) + (profile_hash, ts)
- AST literal lint extended to `backend/app/oms/**` and `backend/app/exchanges/**`

### v0.4.0 (2026-05-24)

#### Features
- Event-driven backtest engine in `backend/app/backtest/` — same-profile-as-live (Constraint #2): pure `Strategy.evaluate(state, params) → list[Order]` consumed by the engine, same `ProfileParams` accessor the live runner will use
- Two engine-validator strategies: `BuyAndHoldStrategy` (single long, holds) and `FundingArbSkeleton` (delta-neutral spot+perp hedge pair; real Strategy A lands Phase 6)
- Constant-bps fill model: per-venue slippage + per-venue/product fees, all profile-driven (`execution.slippage_bps.{venue}`, `execution.fee_bps.{venue}.{product}`)
- `FundingLedger` applies perp funding at venue cadence (data-driven from Parquet), positive funding → longs pay shorts
- `BacktestLoader` streams `MarketSnapshot` per bar from partitioned Parquet via `DuckDBQuery`; `BacktestDataError` on missing data
- Sharpe (24/7 annualised, registry-configurable `metrics.minutes_per_year`), max-drawdown, total-return metrics
- `BacktestRun` ORM + migration 0003: stores `profile_id`/`profile_version`/`profile_hash` (sha256 over canonical-JSON profile config — Constraint #4 audit lock at row creation)
- Async API: `POST /api/v1/backtests` (202 + run_id), `GET /api/v1/backtests/{id}`, `GET /api/v1/backtests` (list with filters)
- Worker job `WORKER_JOB=run_backtest BACKTEST_ID=<uuid>` runs the engine, writes equity-curve Parquet to `data/backtest_runs/{run_id}.parquet`, marks `complete`/`failed`
- `worker-run-backtest` docker-compose service (`profiles: ["jobs"]`) + `just backtest <run_id>` recipe
- AST literal lint extended to `backend/app/backtest/{engine,fills,funding,metrics}.py` + `backend/app/backtest/strategies/**` with carveouts for unit-of-measure constants, subscript indices, and Pow exponents

### v0.3.0 (2026-05-24)

#### Features
- Partitioned Parquet store + DuckDB read layer for historical market data
- Three exchange downloaders: Binance Vision (klines/funding/OI), Bybit Public (klines), Hyperliquid Archive (trades→klines aggregation)
- `MarketDataSource` Protocol + `RetryingFetcher` with exponential backoff
- `DataPipelineService`, `SymbolManifestService` (survivorship-safe), `DataHealthService` (gap detection + event logging)
- Worker job dispatcher via `WORKER_JOB` env; `refresh_data` job; `worker-refresh-data` docker-compose service
- `GET /api/v1/data-health/recent` endpoint
- Alembic migration 0002: `symbol_manifest_snapshots` + `data_health_events` tables

### v0.2.0 (proposed)

#### Features
- FastAPI backend shell + health endpoint + Postgres via Docker Compose
- Multi-service Docker stack: postgres + api + worker + 2× strategy-runner (shared Dockerfile)
- Profile system: three-typed registry, ProfileParams accessor with registry-default fallback, atomic apply_profile with leak-gap prevention
- Pydantic v2 schemas validating profile JSONB with range checks
- StrategyProfileRepository + ProfileService + 6-endpoint HTTP API (create / get / list / active / apply / clone)
- Three named profile fixtures (`paper_safari`, `conservative_funding_only`, `balanced_v1`) + fixture loader CLI
- Strategy Protocol skeleton (MarketState, Action, ActionType) — implementations land in Phase 6+
- AST lint enforcing zero numeric literals in `backend/app/strategies/**` + pytest cross-checks
- Async DB session factory with lifespan management; SQLAlchemy 2.x typed `Mapped`/`mapped_column` models

#### Fixes
- pytest-asyncio cross-loop asyncpg failures via NullPool + function-scoped test engine
- API host port configurable via `$API_PORT` to avoid sibling-project collisions
- Async test client pattern (httpx ASGITransport) for FastAPI + async DB tests
- Ruff per-file-ignores paths corrected for `cd backend` invocation

#### Performance / Refactors
- Applied ruff format across all source files for consistent style baseline
