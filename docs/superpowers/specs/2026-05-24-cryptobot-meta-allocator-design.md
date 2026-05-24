# Cryptobot Phase 18 — Meta-Allocator Design Spec

**Date**: 2026-05-24
**Phase**: 18

## Goal

`MetaAllocator` computes weights across active strategies (currently A + B) using **Sharpe-weighted allocation** over a rolling window. Output: `{"funding_arb": 0.65, "factor_portfolio": 0.35}`. Strategies' position sizes scale by their allocation. Rebalanced on a registry cron cadence.

## Architecture

```python
@dataclass(frozen=True)
class StrategyAllocation:
    strategy_name: str
    weight: float
    sharpe_30d: float

class MetaAllocator:
    def __init__(self, *, params: ProfileParams) -> None: ...
    
    def allocate(
        self,
        *,
        strategy_returns: dict[str, list[float]],  # per-tick returns per strategy
    ) -> tuple[StrategyAllocation, ...]:
        """Compute Sharpe per strategy, normalize positive Sharpes to weights.
        
        Negative-Sharpe strategies get min_weight_pct (already in registry).
        Sum of weights = 1.0.
        """
```

The OMS/runner reads allocations and scales each strategy's `target_notional` by its allocation weight. Phase 18 ships the allocator + tests; full runner integration is opt-in.

## Components

- `backend/app/services/meta_allocator.py`
- `backend/tests/services/test_meta_allocator.py` — 6 tests

## DoD

~290 tests pass. Allocator returns weights summing to 1.0.
