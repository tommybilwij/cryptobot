# Cryptobot Hardening Pass 3 — Strategy B Real Features

**Date**: 2026-05-24

## Goal

Replace stubbed feature pipelines in `FactorPortfolioStrategy`:
1. **30d momentum** — log-return over last 30d of close prices
2. **realized_vol** — already estimator from HP1; just wire it in
3. **volume_rank** — symbol's volume percentile across the universe
4. **Survivorship-safe universe** — load from `SymbolManifestSnapshot` (Phase 3) instead of caller-passed list

## Architecture

### Feature pipeline service

`backend/app/services/feature_pipeline.py`:

```python
class FeaturePipeline:
    """Computes scoring features for a universe of symbols from MarketState + Parquet history."""

    def __init__(self, *, parquet_root: Path, params: ProfileParams) -> None: ...

    def compute_features(
        self, *, venue: str, universe: list[str], state: MarketState
    ) -> dict[str, dict[str, float]]:
        """Returns features keyed by symbol → {momentum_30d, realized_vol, volume_rank, funding_yield}."""
```

`momentum_30d`: read last 30 days of klines via DuckDBQuery, compute log(close_now / close_30d_ago).
`realized_vol`: same window, stdev of log returns × sqrt(525_600).
`volume_rank`: each symbol's volume / max(volumes_in_universe), normalised to [-1, +1].
`funding_yield`: from `state.snapshot.funding_rates`, annualised by per-venue intervals.

### Universe loader

`backend/app/services/universe_loader.py`:

```python
class UniverseLoader:
    """Loads the survivorship-safe universe for a given backtest date."""

    async def for_date(self, *, snapshot_date: date, exchange: str) -> list[str]:
        """Reads SymbolManifestSnapshot. Falls back to live API symbols if no snapshot."""
```

`FactorPortfolioStrategy` is augmented (NOT replaced) to also accept an optional `feature_pipeline: FeaturePipeline | None`. If provided, calls it in `evaluate()` instead of the stub `_features()`.

## Components

- `backend/app/services/feature_pipeline.py` — `FeaturePipeline`
- `backend/app/services/universe_loader.py` — `UniverseLoader`
- `backend/app/strategies/factor_portfolio.py` — accept optional pipeline + universe loader
- `backend/tests/services/test_feature_pipeline.py` — 4 tests (synthetic Parquet)
- `backend/tests/services/test_universe_loader.py` — 3 tests
- `backend/tests/strategies/test_factor_portfolio.py` — 1 test exercising the pipeline path

## DoD

~315 tests pass. Strategy B computes real features when pipeline injected; stub path still works without one.
