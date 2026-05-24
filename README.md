# cryptobot

Multi-strategy crypto trading system. **Phase 1 + Phase 2** ships the foundational scaffolding and the profile system: a FastAPI backend with Postgres, atomic profile apply with leak-gap prevention, AST-enforced "no hardcoded values in strategy code", and a 5-service Docker Compose stack (postgres + api + worker + 2× strategy-runner).

## Architecture

- **Research** — full strategic + architectural research in [`docs/superpowers/research/cryptobot-strategy-architecture.md`](docs/superpowers/research/cryptobot-strategy-architecture.md)
- **Phase 1 + 2 plan** — TDD-style implementation plan in [`docs/superpowers/plans/2026-05-23-cryptobot-strategy-architecture.md`](docs/superpowers/plans/2026-05-23-cryptobot-strategy-architecture.md)

Backend follows FastAPI + SQLAlchemy 2.x async + Pydantic v2 + Alembic. Multi-service via Docker Compose with a shared Python image. Profile system uses three typed registry dicts + Pydantic v2 schemas + Postgres JSONB storage + atomic apply transaction that walks the registry to enforce leak-gap prevention. Constraint #1 (no hardcoded values in strategies) enforced by a custom AST lint script.

## Local dev quickstart

```bash
# 1. Boot postgres
just up

# 2. Install deps + migrate
cd backend && uv sync
cd .. && just mig-up

# 3. Load named profile fixtures
just load-fixtures

# 4. Run the API (dev mode with hot reload)
just api

# 5. In another shell, query
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/strategy-profiles | python3 -m json.tool
```

Or bring up all 5 services via Docker Compose:

```bash
just up-all
docker compose ps
curl http://localhost:8000/api/v1/health   # or $API_PORT if set
```

## Common commands

- `just test` — run pytest (37 tests in Phase 1+2)
- `just typecheck` — mypy `--strict`
- `just lint` — ruff + custom AST lint enforcing no literals in strategies
- `just fmt` — ruff auto-format
- `just mig-new "message"` — generate Alembic migration
- `just mig-up` — apply migrations
- `just load-fixtures` — import the three named profiles into the DB

## Profiles (named, versioned, switchable)

Three named profiles ship under `profiles/`:

| Profile | Strategy A (funding arb) | Strategy B (factor portfolio) | Use |
|---|---|---|---|
| `paper_safari` | enabled, 1% allocation | enabled, 1% allocation | Paper / dry-run reality testing |
| `conservative_funding_only` | enabled, 30% | disabled | First weeks live; A only |
| `balanced_v1` | enabled, 40% | enabled, 20% | Default after both have 30+ days live (Round 5 split favouring A) |

Apply one atomically: `POST /api/v1/strategy-profiles/{id}/apply`.

## Data pipeline (Phase 3)

Historical market data is downloaded from public exchange archives and stored
as partitioned Parquet on local disk under `data/parquet/`. DuckDB queries them
into Polars frames for the backtester and live feature pipeline.

### One-shot manual refresh

```bash
WORKER_JOB=refresh_data just refresh-data
```

### Or via Docker (cron-style)

```bash
docker compose --profile jobs run --rm worker-refresh-data
```

### Querying

```python
from datetime import datetime
from pathlib import Path

from app.market_data.duckdb_query import DuckDBQuery

q = DuckDBQuery(parquet_root=Path("data/parquet"))
df = q.klines("binance", "BTCUSDT", datetime(2024, 1, 1), datetime(2024, 1, 31))
```

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

## OMS + Exchange adapters (Phase 5)

The OMS bridges `Strategy.evaluate()` output to live exchanges with the same
profile-driven contract the backtest uses. Every dispatch is audit-logged with
the active profile's `profile_hash` (Constraint #4).

### Configured venues

- `binance` — Binance spot + USDS-margined perp (HMAC signing)
- `bybit` — Bybit V5 (HMAC signing)
- `hyperliquid` — Hyperliquid perp (EVM-signed)

Phase 5 ships **mocked HTTP only**. Real testnet integration is Phase 7.

### API keys (env-only, never in DB)

```bash
export BINANCE_API_KEY=...
export BINANCE_API_SECRET=...
export BYBIT_API_KEY=...
export BYBIT_API_SECRET=...
export HYPERLIQUID_WALLET_PRIVATE_KEY=...
```

Phase 0 ops checklist covers key creation: withdrawals disabled, IP whitelist.

### Kill switch

```bash
# Flip the active profile's kill switch (halts all OMS dispatches)
curl -X POST http://localhost:8000/api/v1/oms/kill \
  -H "Content-Type: application/json" \
  -d '{"reason":"manual halt"}'

# Check status
curl http://localhost:8000/api/v1/oms/status

# Recent decisions
curl http://localhost:8000/api/v1/decision-audit/recent
```

### Halt classes

- `KillSwitchActive` — `oms.kill_switch_active` flag is set
- `HedgeDriftHalt` — spot/perp position drift > `oms.hedge_drift_halt_pct` (default 5%)
- `ReconciliationDriftHalt` — book vs exchange drift > `oms.reconcile_drift_halt_pct` (default 2%)
- `UnconfiguredVenueError` — strategy emitted an order for a venue not in the OMS exchange map

## Strategy A — Funding Arb (Phase 6)

Delta-neutral funding-rate arbitrage. Goes long spot + short perp when 8-hour
funding is above the entry threshold; closes the hedge when funding decays
below the exit threshold.

### Backtest

```bash
# Profile must exist; use any of the seeded profiles or create your own
curl -X POST http://localhost:8000/api/v1/backtests -H "Content-Type: application/json" -d '{
  "profile_id": "<uuid>",
  "strategy_name": "funding_arb",
  "start_ts": "2024-01-01T00:00:00Z",
  "end_ts":   "2024-01-31T23:59:00Z",
  "venue":    "binance",
  "symbols": ["BTCUSDT"]
}'
```

### Profile knobs (all in the registry)

| Key | Default | Meaning |
|---|---|---|
| `strategies.funding_arb.entry_bps_per_8h` | 8.0 | Open hedge when funding ≥ this |
| `strategies.funding_arb.exit_bps_per_8h` | 4.0 | Close hedge when funding ≤ this |
| `strategies.funding_arb.max_notional_usdc` | 5_000.0 | Hard cap on spot-leg notional |
| `strategies.funding_arb.max_cash_fraction` | 0.5 | Don't deploy >50% of free cash |
| `strategies.funding_arb.intervals_per_year` | 1095.75 | 365.25 × 24 / 8h, for APR conversion |

### Deferred to later phases

- **Live trading** → Phase 7 (testnet) → Phase 8 (dry-run) → Phase 9 (live $500)
- **Kelly / vol-target sizing** → Phase 8 risk machinery
- **Cross-venue best-execution routing** → Phase 9+
- **Multi-symbol portfolios** → Phase 13+

## Testnet integration (Phase 7)

REST adapters are now production-shaped: `fetch_positions`, `fetch_order`, and `fetch_funding_rate` all hit real endpoints. Hyperliquid signs via EIP-712 typed-data. `LiveStateFetcher` builds a `MarketState` from any `Exchange` adapter — the live analogue of `BacktestLoader`.

### Required env vars

```bash
# Binance Spot Testnet + Futures Testnet keys
export BINANCE_API_KEY=...
export BINANCE_API_SECRET=...

# Bybit V5 testnet keys (api-testnet.bybit.com)
export BYBIT_API_KEY=...
export BYBIT_API_SECRET=...

# Hyperliquid testnet wallet (EVM private key; testnet at app.hyperliquid-testnet.xyz)
export HYPERLIQUID_WALLET_PRIVATE_KEY=0x...
```

### Health check

```bash
curl http://localhost:8000/api/v1/exchanges/health
```

Returns per-venue reachability + balance via PaperExchange. Real-adapter swap-in lands in Phase 8.

### Testnet smoke tests

```bash
# Deselected by default; opt in with -m slow + env keys
cd backend && uv run pytest -m slow tests/integration/test_binance_testnet_smoke.py -v
cd backend && uv run pytest -m slow tests/integration/test_bybit_testnet_smoke.py -v
cd backend && uv run pytest -m slow tests/integration/test_hyperliquid_testnet_smoke.py -v

# Hyperliquid order-placement calibration (opt-in within opt-in)
HYPERLIQUID_SMOKE_PLACE_ORDER=1 cd backend && uv run pytest -m slow tests/integration/test_hyperliquid_testnet_smoke.py::test_hyperliquid_testnet_place_tiny_order_calibrates_signing -v
```

Each smoke test skips cleanly when the relevant env keys are missing. HL signing uses a Phase 7 JSON-stable EIP-712 connection-id formula; if HL testnet rejects the signature, calibrate against the actual docs scheme (msgpack-encoded action + keccak) — verified via the order-placement smoke.

### Deferred to Phase 8+

- Live runner loop (continuous strategy → OMS → exchange) → Phase 8
- Real-adapter wiring in `/health` endpoint (currently PaperExchange) → Phase 8
- WebSocket fills → Phase 9+
- Mainnet → Phase 9

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

## First live $500 (Phase 9 runbook)

Phase 9 ships the safety infrastructure for real-money trading. The first
$500 trade is an OPS action — flip flags, fund a wallet, monitor closely.

### Pre-flight checklist (DO ALL OF THESE)

- [ ] Phase 7 testnet smoke tests passed against your testnet wallets
- [ ] Phase 8 dry-run loop ran for ≥ 24h with no halts
- [ ] All halt classes tested by deliberately triggering them in dry-run
- [ ] Webhook URL configured (`alerts.webhook_url`) and verified working
- [ ] You can stop the runner via `POST /api/v1/live/stop` within 10s
- [ ] Drawdown brake trigger (`risk.drawdown_brake.trigger_pct`) reviewed and set
- [ ] $500 USDC deposited to ONLY the configured venue (start with one, not all three)
- [ ] API keys: withdrawals disabled, IP-whitelisted to deploy host

### Flag-flip sequence

1. Set `exchanges.{venue}.use_testnet=False` on active profile (switches URLs to mainnet)
2. Set `live.dry_run_mode=False` (switches PaperExchange → real adapter)
3. Restart the runner: `docker compose --profile live up -d --force-recreate worker-live-trade`
4. Tail logs: `docker compose logs -f worker-live-trade`
5. Monitor `/api/v1/live/status` every minute for the first hour

### Rollback (immediate stop)

```bash
curl -X POST http://localhost:8000/api/v1/oms/kill   # halt OMS dispatches mid-flight
curl -X POST http://localhost:8000/api/v1/live/stop  # exit the runner loop
```

### Webhook payload shape

```json
{
  "severity": "critical | warning | info",
  "event": "DrawdownBrakeHalt | KillSwitchActive | HedgeDriftHalt | ReconciliationDriftHalt | heartbeat",
  "details": { "...": "event-specific" },
  "ts": "2026-05-24T05:55:00Z"
}
```

Set `alerts.webhook_url` to your Discord/Slack/Telegram webhook BEFORE flipping flags. Halt classes auto-alert at `severity=critical`; reconciliation drift at `warning`; heartbeats are opt-in via `alerts.send_heartbeats=True`.

### Safe-by-default toggles

| Key | Default | Production value |
|---|---|---|
| `live.enabled` | `False` | `True` (start the loop) |
| `live.dry_run_mode` | `True` | `False` (real money) |
| `exchanges.{venue}.use_testnet` | `True` | `False` (mainnet URLs) |
| `alerts.webhook_url` | `""` | your webhook (REQUIRED for live) |

Adapter factory falls back to PaperExchange if env keys are missing — even with all flags flipped, a misconfigured deploy can't accidentally hit live without keys.

### When to scale beyond $500

After the first $500 runs for 1-2 weeks with no halts, no manual intervention, and positive funding-arb P&L net of fees → Phase 10+ (Kelly sizing + vol targeting + capital scale-up).

## Layout

```
backend/
├── app/
│   ├── api/             # HTTP routes
│   ├── models/          # SQLAlchemy ORM
│   ├── schemas/         # Pydantic v2 (boundary validation)
│   ├── profile/         # Registry, ProfileParams, apply mechanism
│   ├── repositories/    # DB queries
│   ├── services/        # Business logic
│   ├── strategies/      # CI-lint-protected: NO literals allowed
│   ├── worker/          # Background-job stub
│   └── strategy_runner/ # Per-strategy host stub
├── alembic/
├── scripts/
└── tests/

profiles/                # Named JSON fixtures
scripts/                 # Repo-level scripts (AST lint)
docs/superpowers/        # Research + plans
```

## What's next (out of scope for Phase 1+2+3)

Future phases ship via their own plans in `docs/superpowers/plans/`:

- **Phase 4** — Backtester with funding accrual + survivorship-safe universe
- **Phase 5** — Exchange adapter layer (CCXT + HL SDK) + idempotent OMS
- **Phase 6+** — Strategy implementations (alt funding arb, cross-sectional factor portfolio)
- **Phase 8** — Next.js Strategy Lab UI
- **Phase 9** — Production ops + monitoring
