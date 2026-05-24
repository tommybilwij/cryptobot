# Cryptobot Phase 14 — Composite Scoring Engine Design Spec

**Date**: 2026-05-24
**Phase**: 14

## Goal

Build the **composite scoring engine** for Strategy B (factor portfolio, Phase 15). Computes a weighted-sum score over multiple components (momentum, mean-reversion, volume, funding-stress, etc.) for each symbol in a universe. Registry-driven weights/thresholds/max_scores.

Pattern reference: `../stockbot/backend/app/services/scoring.py` (load via Read tool if needed).

## Architecture

`backend/app/services/scoring.py`:

```python
@dataclass(frozen=True)
class ComponentScore:
    name: str
    raw: float        # raw input value
    score: float      # normalised (-max_score, +max_score)
    weight: float
    weighted: float   # score * weight

@dataclass(frozen=True)
class CompositeScore:
    symbol: str
    total: float
    components: tuple[ComponentScore, ...]
    bucket: str       # "strong_buy" | "buy" | "watch" | "neutral" | "skip"


class ScoringEngine:
    def __init__(self, *, params: ProfileParams) -> None: ...
    
    def score(
        self, *, symbol: str, features: dict[str, float]
    ) -> CompositeScore: ...
```

Components Phase 14 ships:
- **momentum_30d** — 30d return
- **funding_yield** — annualised funding rate
- **realized_vol** — 30d annualised vol (inverse weight — low vol scores higher)
- **volume_rank** — symbol's volume percentile in the universe

Each has registry-driven max_score + weight + linear-clamp normalisation. Final bucket comes from `strategies.factor_portfolio.scoring.thresholds.{strong_buy, buy, watch}`.

## Components

- `backend/app/services/scoring.py` — `ScoringEngine` + dataclasses
- `backend/tests/services/test_scoring.py` — 8 tests
- Registry additions: per-component max_score + weight (4 components × 2 = 8 numeric keys)

## DoD

~265 tests pass. Scoring engine returns deterministic CompositeScore.
