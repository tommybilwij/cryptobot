# Cryptobot Phase 10 — Risk Machinery (Kelly + Vol Target) Design Spec

**Date**: 2026-05-24
**Phase**: 10
**Blocks**: Phase 11+

## Goal

Replace Phase 6's simple `min(max_notional, cash * fraction)` sizing with **Kelly fraction** + **vol targeting**. Strategy A reads a unified `risk.SizingService.size(funding_rate, vol, cash, peak_equity) → notional` instead of computing inline.

## Architecture

`backend/app/risk/sizing.py`:

- **Kelly fraction**: `kelly = (funding_rate * intervals_per_year - rf) / (vol ** 2)` clamped to `[0, risk.kelly.baseline_cap]`.
- **Vol targeting**: scale to `risk.vol_target.target_pct / realized_vol`. Default target 1.5%.
- **Drawdown brake mult**: from peak — between `trigger_pct` and `full_pct`, multiplier decreases linearly to `min_mult` (0.25).
- **Final notional**: `cash * min(kelly_frac, vol_target_frac) * drawdown_mult`, capped by `funding_arb.max_notional_usdc`.

All knobs already in registry (Phase 1+2 seeded them).

## Components

- `backend/app/risk/sizing.py` — `SizingService.compute_notional(...)` pure function
- `backend/app/strategies/funding_arb.py` — replace inline sizing with `SizingService`
- `backend/tests/risk/test_sizing.py` — 6 tests

## Tests

- Kelly = 0 when funding ≤ rf → no position
- Kelly clipped at baseline_cap (default 2%)
- Vol target inverse to realized vol
- Drawdown mult = 1 above trigger, = min_mult at full halt
- Final notional respects max_notional cap
- Updated FundingArb hedge-open test still passes (new sizing gives non-zero qty in typical case)

## DoD

~250 tests pass. mypy + ruff + AST lint clean. FundingArb still trades sensibly.
