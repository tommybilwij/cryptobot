# Changelog

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
