# Changelog

### v0.10.0 (2026-05-24)

#### Features
- `SizingService` in `backend/app/risk/sizing.py` — unified Kelly fraction + vol target + drawdown brake multiplier. Pure function, all knobs from the profile registry (Constraint #1)
- Kelly fraction: `(funding_rate * intervals_per_year) / vol^2 * risk.kelly.fraction`, clamped to `risk.kelly.baseline_cap` (default 2%)
- Vol target: `risk.vol_target.target_pct / realized_vol`, same baseline cap
- Drawdown brake multiplier: 1.0 above `risk.drawdown_brake.trigger_pct`, linear ramp to `risk.drawdown_brake.min_mult` (0.25) at `risk.drawdown_brake.full_pct` (15%)
- `FundingArbStrategy._open_hedge` routes through `SizingService` when `risk.kelly.enabled=True`; opt-in (default 0.0) so existing tests + live behaviour unchanged
- Phase 10 simplification: vol fixed at 0.6 placeholder, equity == cash_quote (no MTM). Real estimators in Phase 11+
- 6 new tests covering: zero funding → zero notional, Kelly clipped at baseline cap, zero vol guard, drawdown ramp at partial / full halt, max_notional cap

### v0.9.0 (2026-05-24)

#### Features
- `exchange_factory.build_exchange()` — dry-run-aware adapter builder. Returns PaperExchange in dry-run mode OR a real adapter from env keys, with paper fallback when keys are missing (defence in depth)
- `Alerter` service — POSTs halt-class events to `alerts.webhook_url` (Discord/Slack/Telegram-compatible). Empty URL = no-op; never throws (swallows webhook failures so the runner stays alive)
- `live_trade` worker wires real adapters (Binance + Bybit + Hyperliquid) via the factory; LiveRunner calls Alerter on `DrawdownBrakeHalt`, `KillSwitchActive`, `HedgeDriftHalt`, `ReconciliationDriftHalt`, and opt-in hourly heartbeats
- `/api/v1/exchanges/health` uses factory — pings real adapters when env keys present, falls back to PaperExchange otherwise
- 4 new alerts registry keys: `alerts.webhook_url`, `alerts.heartbeat_severity`, `alerts.send_heartbeats`, `alerts.timeout_s`
- README Phase 9 runbook: pre-flight checklist, flag-flip sequence, rollback, webhook payload shape
- 12 new tests (4 registry + 3 alerter + 5 factory + 1 alerter-on-drawdown)

### v0.8.0 (2026-05-24)

#### Features
- `LiveRunner` service in `backend/app/services/live_runner.py` — continuous tick loop tying LiveStateFetcher + FundingArbStrategy + OMS together with hourly snapshot logging
- `DrawdownBrake` in `backend/app/risk/drawdown_brake.py` — halts trading when equity drops > `risk.drawdown_brake.trigger_pct` (default 5%) from rolling peak
- `WORKER_JOB=live_trade` worker job + `worker-live-trade` docker-compose service (`profiles: ["live"]`) + `just live-trade` recipe
- `GET /api/v1/live/status` reports `enabled`, `dry_run_mode`, last tick, equity, peak, drawdown_pct
- `POST /api/v1/live/stop` flips `live.enabled=False` on active profile (bumps version)
- 7 new registry keys: 3 numeric (`live.tick_interval_s`, `live.snapshot_interval_s`, `live.cold_start_grace_s`), 2 bool (`live.enabled=False`, `live.dry_run_mode=True`), 1 string (`live.venue`), 1 numeric (`risk.drawdown_brake.peak_equity`)
- Safe-by-default: `live.enabled=False` + `live.dry_run_mode=True` baked in; firing the worker without flipping flags = no-op
- 14 new tests (5 drawdown brake + 5 live runner + 1 worker dispatch + 3 API)

### v0.7.0 (2026-05-24)

#### Features
- All 3 REST adapters' `fetch_positions` + `fetch_order` non-stub implementations (Binance `/fapi/v2/positionRisk`, Bybit `/v5/position/list`, Hyperliquid `clearinghouseState` parsing)
- New `Exchange.fetch_funding_rate(symbol) -> float | None` Protocol method; all 4 adapters implement (Binance `/fapi/v1/premiumIndex`, Bybit `/v5/market/funding/history`, HL `/info` fundingHistory, paper returns configured rate)
- Hyperliquid `place_order` upgraded from EIP-191 personal_sign to EIP-712 typed-data signing (Phase 7 JSON-stable connection-id formula; needs live testnet calibration to be production-correct)
- `LiveStateFetcher` service: builds `MarketState` from any `Exchange` (live analogue of `BacktestLoader`)
- `GET /api/v1/exchanges/health` endpoint: per-venue reachability + balance + testnet flag
- 7 new exchange-URL string registry keys (`exchanges.{venue}.{spot|perp}_base_url_{testnet|mainnet}`)
- 3 slow-marker testnet smoke tests (Binance + Bybit + Hyperliquid), opt-in via env keys; HL order-placement calibration gated behind `HYPERLIQUID_SMOKE_PLACE_ORDER=1`

### v0.6.0 (2026-05-24)

#### Features
- Strategy A — `FundingArbStrategy` in `backend/app/strategies/funding_arb.py`: delta-neutral long-spot + short-perp when 8h funding ≥ entry threshold (default 8 bps); closes hedge when funding decays below exit threshold (default 4 bps); hysteresis prevents churn
- `MarketSnapshot.funding_rates: dict[tuple[str, str], float]` field (default_factory dict) — backward-compatible
- `BacktestLoader` populates per-tick funding rates from Parquet alongside klines
- Strategy registered in `StrategyRegistry.default()` as `"funding_arb"`; `BacktestService` routes it with `products=["spot", "perp"]`
- 3 new registry numeric keys consolidated under existing `strategies.funding_arb.*` namespace: `max_notional_usdc`, `max_cash_fraction`, `intervals_per_year` (Phase 6 sizing knobs alongside Phase 1+2 thresholds)
- 11 unit tests covering 4-state machine (flat / hedged / orphan spot / orphan perp), sizing caps, and a 6-tick hysteresis sweep
- 1 engine E2E test runs the strategy over hand-crafted Parquet + funding event

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
