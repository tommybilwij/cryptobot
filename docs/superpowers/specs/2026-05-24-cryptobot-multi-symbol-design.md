# Cryptobot Phase 12 — Multi-Symbol Strategy A Design Spec

**Date**: 2026-05-24
**Phase**: 12

## Goal

`FundingArbStrategy` currently takes a single `symbol` constructor arg. Phase 12 generalises to **multi-symbol** so one strategy instance trades a configurable universe (e.g. `["BTCUSDT", "ETHUSDT", "SOLUSDT"]`). Each symbol is evaluated independently per tick; orders aggregate into one list.

## Architecture

`FundingArbStrategy.__init__(*, venue: str, symbols: list[str])` (changed from `symbol`).

`evaluate(state, params)` loops over `symbols`, calls a new private `_evaluate_one(state, params, symbol) → list[Order]` (the existing single-symbol logic refactored), accumulates orders.

`MultiVenueCashLedger` (Phase 5) already supports per-symbol attribution; the strategy splits cash equally across active symbols: `cash_per_symbol = cash * 1/N` where N is `len(symbols)`. Sizing service caps each symbol's spot leg at this fraction.

## Components

- `backend/app/strategies/funding_arb.py` — refactor: `symbol` → `symbols: list[str]`; new `_evaluate_one`
- `backend/app/backtest/registry.py` — `StrategyRegistry.build("funding_arb", venue, symbols)` accepts list (handle scalar for backward-compat)
- `backend/app/services/backtest_service.py` — pass `run.symbols` as list (already a list field on BacktestRun ORM)
- `backend/app/worker/jobs/live_trade.py` — read `strategies.funding_arb.symbols` from registry (new dict default = `["BTCUSDT"]`)
- `backend/tests/strategies/test_funding_arb.py` — add 2 multi-symbol tests
- New registry key: `strategies.funding_arb.symbols` (DICT-type holding the list)

## DoD

~259 tests pass. Strategy works with 1 or N symbols. Existing single-symbol tests still pass.
