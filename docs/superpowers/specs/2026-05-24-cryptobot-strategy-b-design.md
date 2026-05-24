# Cryptobot Phase 15 — Strategy B (Factor Portfolio) Design Spec

**Date**: 2026-05-24
**Phase**: 15

## Goal

`FactorPortfolioStrategy` — long top-decile + (optionally) short bottom-decile of a multi-symbol universe ranked by `ScoringEngine` (Phase 14). Single rebalance per call: close stale positions, open new top-N.

## Architecture

```python
class FactorPortfolioStrategy:
    name = "factor_portfolio"

    def __init__(self, *, venue: str, universe: list[str]) -> None: ...

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        # 1. Compute scores for every symbol in universe
        # 2. Sort by composite total
        # 3. Top N (top_decile_pct * len(universe)) → target longs
        # 4. (If shorts_enabled) bottom N → target shorts
        # 5. Diff current positions vs target → emit close/open orders
```

Features are pulled from `MarketState.snapshot.bars` (close prices for momentum) + `MarketState.snapshot.funding_rates` (funding_yield). `realized_vol` and `volume_rank` are computed from bar data when available, else default to 0.0.

For Phase 15: ship the strategy + registry tests. Real feature pipelines (rolling vol, volume percentile across universe) defer to Phase 16+ (IC discipline).

## Components

- `backend/app/strategies/factor_portfolio.py` — strategy class
- `backend/app/backtest/registry.py` — register "factor_portfolio"
- `backend/tests/strategies/test_factor_portfolio.py` — 6 tests

## DoD

~272 tests pass. Strategy registered + works in unit tests with synthetic state.
