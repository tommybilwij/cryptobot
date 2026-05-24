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
