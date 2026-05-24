# Changelog

### v1.9.0 (2026-05-24) — Hardening Pass 10: WS into OMS + listen-key refresh + load harness

#### Features
- OMS accepts optional `ws_clients: dict[str, WSClient]` per-venue. When a venue has a client, `_poll_until_terminal` waits on `WSClient.next_fill_for(order_id, timeout_s=oms.max_fill_wait_s)` for a push fill, falling back to REST `fetch_order` polling on WS timeout
- `_status_from_ws_msg` normalises Binance (`executionReport`), Bybit V5 execution, and Hyperliquid (`userFills`) message shapes to a unified `OrderStatus`
- `ListenKeyKeepalive` (`backend/app/exchanges/ws/binance_listen_key.py`) — async PUT-every-30-min keepalive task for the Binance user-data listenKey. Refresh errors are logged and retried; WS disconnect remains the source of truth for key death
- Load test harness (`backend/tests/load/test_concurrent_backtests.py`, `just load-test`) — N=5 sequential `BacktestService.execute` runs as a smoke for resource-handle accumulation. Slow-marker; deselected by default
- 335 prior + 2 OMS WS dispatch tests + 1 listen-key refresh test = 338 tests pass; 1 slow load test deselected

### v1.8.0 (2026-05-24) — Hardening Pass 9: frontend polish

#### Features
- Prettier config (`frontend/.prettierrc`, `frontend/.prettierignore`) — unblocks the dev-toolkit-react-tailwind pre-commit gate on TSX commits. Adds `format` / `format:check` scripts to `package.json`
- Vitest scaffold (`frontend/vitest.config.ts`, `frontend/vitest.setup.ts`) — jsdom environment, `@`-alias resolution mirroring the Next.js setup, jest-dom matchers via setup file. Adds `test` / `test:ui` scripts and devDependencies for vitest + @testing-library/react + jsdom
- Three starter tests: `Sparkline.test.tsx` covers the "not enough data" placeholder and the SVG polyline render; `api.test.ts` covers the apiGet base-URL prefix + JSON path
- Profile editor at `/profiles/[id]/edit` — JSON textarea + Save button that POSTs to `/api/v1/strategy-profiles/<id>/apply`. Cancels back to `/profiles`. `/profiles` list gains an `edit` link per row
- Equity drilldown at `/live/ticks` — polls `/api/v1/decision-audit/recent?decision_type=snapshot&limit=200` every 5s and renders one line per snapshot (ts, equity, cash, peak, reconciliation status). `/live` page links to it via "view tick history"
- No backend changes; 335 tests still pass

### v1.5.0 (2026-05-24) — Hardening Pass 6: frontend pages wired up

#### Features
- `/profiles` page wired — lists `GET /api/v1/strategy-profiles`, shows name + version + active badge, click-to-expand renders the profile's `config` JSON inline. Polls every 5s
- `/live` page wired — polls `GET /api/v1/live/status` every 5s, renders enabled/dry-run/venue badges + last-tick + reconciliation status. Stop button POSTs to `/api/v1/live/stop`. Equity block shows last/peak/drawdown with red highlight when drawdown < -2%
- `/audit` page wired — polls `GET /api/v1/decision-audit/recent?limit=50` every 5s with `strategy_name` text filter and `decision_type` select (`order` / `snapshot` / all). Per-row: ts, strategy, reconciliation status (green/yellow/red), profile version, decision type, orders/fills count, optional reason
- `/exchanges` page wired — polls `GET /api/v1/exchanges/health` every 5s, renders one row per venue with configured / mainnet-vs-testnet / reachable badges + quote balance + last error
- `Sparkline` component (`frontend/src/components/Sparkline.tsx`) — dependency-free inline SVG polyline. Auto-scales y to value range, green stroke when last >= first else red, prints last value top-right. Renders "Not enough data" placeholder when fewer than 2 points
- Equity sparkline on `/live` pulls the last 100 `decision_type=snapshot` audit rows, extracts `input_state.equity`, reverses to chronological order before rendering
- No backend changes; 325 tests still pass

### v1.2.0 (2026-05-24) — Hardening Pass 3: Strategy B real features

#### Features
- `FeaturePipeline` (`backend/app/services/feature_pipeline.py`) — computes real per-symbol features for the factor portfolio from Parquet history + `MarketState`: `momentum_30d` (log-return over 30d), `realized_vol` (annualised stdev of 1m log returns, ×√525_600), `volume_rank` (summed window volume / universe max), `funding_yield` (current funding × per-venue `funding_intervals_per_year`). Missing-history symbols degrade to zeroed features instead of raising
- `UniverseLoader` (`backend/app/services/universe_loader.py`) — survivorship-safe universe load from `SymbolManifestSnapshot` by `(snapshot_date, exchange)`. Missing snapshot returns `[]` so callers can choose whether to backfill or fail
- `FactorPortfolioStrategy` accepts an optional `feature_pipeline=FeaturePipeline(...)`. When injected, `evaluate()` calls it once per tick instead of the legacy stub `_features()`. Backward compatible — existing tests construct the strategy without a pipeline and still pass
- 8 new tests (4 `test_feature_pipeline`, 3 `test_universe_loader`, 1 `test_factor_portfolio` exercising the injected-pipeline path). 305 prior + 8 = 313 tests pass

### v1.1.0 (2026-05-24) — Hardening Pass 2: state persistence

#### Features
- `runner_state` table (key/value JSONB) backs restart-safe runner state. New ORM `RunnerState`, migration `0005_create_runner_state`, and `RunnerStateService.get/set` (upsert) in `backend/app/services/runner_state.py`
- `LiveRunner` accepts optional `RunnerStateService`. `hydrate()` seeds the drawdown brake's high-water mark from the persisted `peak_equity` row; every tick writes back when the brake's peak strictly ratchets up. Restarts no longer reset the brake to the profile registry default
- `DrawdownBrake.set_peak()` exposes a setter so hydration can seed the peak without bypassing the brake's invariant
- `ICTracker` and `ComponentGraveyard` accept optional `RunnerStateService` and gain `async persist()` / `async hydrate()`. IC history and buried components survive restarts via the `ic_tracker` and `component_graveyard` keys
- 10 new tests (3 service round-trip, 2 runner hydrate/persist, 4 risk round-trip — IC tracker + graveyard, plus the bump). 305 tests pass (previously 295)

### v1.0.0 (2026-05-24) — feature complete

#### Features
- Structured JSON logging — `backend/app/logging_config.py` provides `JsonFormatter` + `setup_logging()` that wires the root logger to a stdout `StreamHandler` emitting one JSON line per record (`ts`, `level`, `logger`, `msg`, plus any extras + exception info). `app.main` calls `setup_logging()` at import time so every uvicorn/FastAPI/SQLAlchemy log lands as structured JSON, ready for Loki/CloudWatch/journald aggregation
- Prometheus `/api/v1/metrics` endpoint — `backend/app/api/metrics.py` exposes `cryptobot_up` (gauge), `cryptobot_decision_audit_total` (counter from `DecisionAuditEntry` row count), `cryptobot_backtest_runs_total` (counter from `BacktestRun` row count), `cryptobot_oms_kill_switch_active` (gauge from active profile). Plain-text Prometheus 0.0.4 format with `# HELP` / `# TYPE` headers, scrape-able on the same port as the API
- `docs/DEPLOY.md` — production deploy runbook covering env-var checklist, bare-metal install via uv, Docker Compose with `--profile live`, Postgres 6h pg_dump cron to S3, log aggregation patterns (Loki / journald / CloudWatch), Prometheus scrape config, and the rollback procedure (`/oms/kill` → `/live/stop` → compose stop → manual venue close)
- 2 new tests in `tests/api/test_metrics.py` (format + HELP/TYPE assertions). 290 prior + 2 new = 292 tests pass
- **v1.0.0 — feature complete.** Subsequent versions are operational tuning (parameter tweaks, bug fixes, profile updates), not new feature code

### v0.19.0 (2026-05-24)

#### Features
- Strategy Lab UI scaffold — Next.js 15 + Tailwind frontend in `frontend/`. App Router with top-bar nav (`/`, `/profiles`, `/oms`, `/live`, `/audit`, `/exchanges`)
- `/oms` is wired and live: polls `GET /api/v1/oms/status` every 5s, renders kill-switch state, active profile id/version, last dispatch ts + reconciliation status, and per-venue configured / testnet badges. Kill button POSTs to `/api/v1/oms/kill` with a manual reason
- `frontend/src/lib/api.ts` — minimal `apiGet` / `apiPost` helpers reading `NEXT_PUBLIC_API_BASE_URL` (defaults to `http://localhost:8000`). `cache: "no-store"` on every fetch — no Next.js caching footgun
- `StatusBadge` shared component for green/dim active-state pills used across the OMS page
- `/profiles`, `/live`, `/audit`, `/exchanges` ship as Phase 20+ placeholders so the nav resolves now and the routes have an obvious slot to land into later
- Backend CORS — `CORSMiddleware` added in `backend/app/main.py` with `allow_origins=["http://localhost:3000"]` so the dev UI can reach the API
- No new backend tests; existing 290 tests still pass. No frontend test infra yet — added in a later phase

### v0.16.0 (2026-05-24)

#### Features
- `ICTracker` in `backend/app/risk/ic_tracker.py` — records `(score, forward_return)` per scoring component, computes rolling Spearman rank correlation (pure-Python; no scipy dep). `deprecate_if_drifting()` auto-buries components whose IC falls below threshold
- `ComponentGraveyard` in `backend/app/risk/component_graveyard.py` — in-memory set of deprecated scoring components with `add` / `is_buried` / `list` / `revive` API
- `ScoringEngine` accepts optional `graveyard: ComponentGraveyard | None`; buried components are skipped (treated as 0) on each `score()` call — surviving components contribute their normal weighted contribution
- Average-rank Spearman handles ties correctly; degenerate input (n < 2 or zero variance) returns 0.0
- 8 new tests: 3 graveyard (`test_component_graveyard.py`), 4 IC tracker (`test_ic_tracker.py`), 1 scoring engine integration. 272 prior + 8 = 280 tests pass

### v0.15.0 (2026-05-24)

#### Features
- `FactorPortfolioStrategy` (Strategy B) — ranks a configured universe by `ScoringEngine` composite total, opens equal-weight longs in the top decile, and (if `strategies.factor_portfolio.shorts_enabled` > 0) opens equal-weight shorts in the bottom decile. Single rebalance per `evaluate()` call: stale positions get close orders, new top/bottom symbols get open orders sized as `cash_quote / target_count` over the current spot close
- Registered as `"factor_portfolio"` in `StrategyRegistry.default()` — the same name the API endpoint and worker job validate against, so live + backtest instantiate from the same registry
- Phase 15 simplification: only the `funding_yield` feature is wired to real data (per-tick funding × `strategies.funding_arb.intervals_per_year`); `momentum_30d` / `realized_vol` / `volume_rank` default to 0.0 until Phase 16+ adds the rolling/cross-sectional pipelines
- 6 new tests in `tests/strategies/test_factor_portfolio.py` covering empty universe, top-decile selection across a 10-symbol universe, missing funding data, missing bars, stale-long close-out, and registry resolution. 266 prior + 6 = 272 tests pass

### v0.14.0 (2026-05-24)

#### Features
- `ScoringEngine` for Strategy B (factor portfolio) — composite weighted-sum score over 4 components: `momentum_30d`, `funding_yield`, `realized_vol`, `volume_rank`. Each component has a registry-driven `max_score` (raw → normalised clamp) and `weight` (normalised → weighted contribution)
- `ComponentScore` / `CompositeScore` dataclasses (frozen) — `CompositeScore` carries `symbol`, `total`, `components` tuple, and a `bucket` (`strong_buy` / `buy` / `watch` / `neutral` / `skip`) sourced from the existing `strategies.factor_portfolio.scoring.thresholds.*` registry block
- `realized_vol` uses inverted normalisation (lower vol → higher score; centred at 0.5 annualised); all other components use plain linear `raw * max_score` clamped into `[-max_score, +max_score]`
- 8 new registry keys (`strategies.factor_portfolio.scoring.{component}.{max_score,weight}` for the 4 components); 1 registry test + 8 scoring engine tests. 257 prior + 1 + 8 = 266 tests pass
- No Strategy B wiring yet — Phase 15 consumes `ScoringEngine` to drive top/bottom decile selection over the universe

### v0.13.0 (2026-05-24)

#### Features
- Per-strategy sub-account API keys for venue isolation. `Settings` gains 7 optional `_funding_arb` / `_factor_pf` suffixed fields (`binance_api_key_funding_arb`, `binance_api_secret_funding_arb`, `binance_api_key_factor_pf`, `binance_api_secret_factor_pf`, `bybit_api_key_funding_arb`, `bybit_api_secret_funding_arb`, `hyperliquid_wallet_private_key_funding_arb`)
- `exchange_factory.build_exchange()` accepts a new `sub_account: str | None` kwarg; helper `_resolve_key()` returns the strategy-specific key when populated, falls back to the base field otherwise. Sub-account string is normalized (dashes → underscores) so profile values like `strategy-a-arb` map cleanly to field names
- `live_trade` worker reads `strategies.funding_arb.sub_account` from the registry and threads it through to every venue adapter — same profile, same sub-account routing for backtest and live (Constraint #2)
- 2 new tests in `test_exchange_factory.py`: `test_factory_uses_sub_account_keys_when_present`, `test_factory_falls_back_to_base_keys_when_sub_empty`. 255 prior + 2 new = 257 tests pass
- Wiring pattern extends trivially to Bybit and Hyperliquid by the same `_resolve_key` lookup; only Binance is exercised by tests in this phase

### v0.12.0 (2026-05-24)

#### Features
- `FundingArbStrategy` now accepts `symbols: list[str]` instead of `symbol: str` — the strategy loops over its configured symbols on every tick and emits orders per symbol
- Cash splits equally across the configured symbols when opening a hedge (`cash_per_symbol = state.cash_quote / len(symbols)`), so a 2-symbol profile with $1000 cash sizes each leg from $500
- Backward-compat: a single-element list `symbols=["BTCUSDT"]` is functionally identical to the pre-Phase-12 single-symbol mode; all 10 existing single-symbol tests pass unchanged after the constructor swap
- `BacktestService` branches on `strategy_name`: `funding_arb` receives the full `symbols` list, other (still single-symbol) strategies receive `run.symbols[0]`
- `live_trade` worker wraps `strategies.funding_arb.default_symbol` into `symbols=[symbol]`; future phase will read a registry list directly
- 2 new tests: `test_multi_symbol_emits_orders_per_symbol` (2 symbols × spot+perp = 4 orders), `test_multi_symbol_splits_cash` (each symbol sized from `cash / N`)

### v0.11.0 (2026-05-24)

#### Features
- `WSClient` Protocol in `backend/app/exchanges/ws/base.py` — push-based fill stream contract (`connect`, `subscribe`, `iter_messages`, `next_fill_for`, `close`); cuts fill-confirmation latency from ~1s REST poll to ~50ms WS push
- `PaperWSClient` in `backend/app/exchanges/ws/paper_ws.py` — in-memory `asyncio.Queue` implementation for tests; `push()` helper enqueues messages, `next_fill_for()` filters by `order_id` with timeout
- Venue stubs `BinanceWSClient` / `BybitWSClient` / `HyperliquidWSClient` — `name` attribute + `NotImplementedError` from every Protocol method; real testnet WS calibration is opt-in Phase 11+ slow-test scope
- 4 new tests covering: connect/close, matching-order return, timeout returns `None`, skipping unmatched messages
- No OMS integration yet — Phase 12+ wires `ws_client` parameter into `OMS.dispatch()`

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
