# Cryptobot Hardening Pass 7 — Quick Wires

**Date**: 2026-05-24

## Goal

Close the "shipped but not wired" gaps from HP1/HP3 + drop the orphan Phase 3 index + tune DB pool:

1. **`RollingVolEstimator` → `LiveRunner`** — populate `MarketSnapshot.realized_vols` per tick from running estimator
2. **`UniverseLoader` → `BacktestService`** — use survivorship-safe universe for Strategy B backtests
3. **Drop orphan `ix_strategy_profiles_active`** — migration 0006
4. **DB connection pool sizing** — configurable via env

## Components

- `backend/app/services/live_runner.py` — owns a `RollingVolEstimator`, records bar close + injects `realized_vols` into snapshot
- `backend/app/services/backtest_service.py` — for `factor_portfolio`, build a `FeaturePipeline` + (optionally) read manifest via `UniverseLoader`
- `backend/alembic/versions/0006_drop_orphan_strategy_profile_index.py` — `op.drop_index("ix_strategy_profiles_active")`
- `backend/app/deps.py` — pool_size + max_overflow from env via Settings
- Tests for each

## DoD

~332 tests pass. Orphan index gone from DB. Pool sizing configurable.
