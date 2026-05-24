# Cryptobot Hardening Pass 1 — Correctness & Calibration

**Date**: 2026-05-24

## Goal

Fix four correctness gaps that block real-money trading:
1. **HL EIP-712 signing** — current JSON-stable hash will be rejected by Hyperliquid. Calibrate to msgpack-encoded action + keccak per HL docs.
2. **Per-venue funding cadence** — HL pays hourly (8760 intervals/year), Binance perp pays 8h (1095.75). Single hardcoded constant mis-sizes Strategy A.
3. **Real `realized_vol` estimator** — current code passes `0.6` placeholder to SizingService when Kelly enabled. Compute rolling 30-bar annualised stdev.
4. **Basis-blowout halt** — `strategies.funding_arb.basis_halt_bps` registry key exists but no code reads it. Add halt when |spot - perp| / spot > threshold.

## Architecture

### HL EIP-712 fix

`hyperliquid.py::_sign_l1_action` switches to msgpack action encoding:
- Add `msgpack` dep
- Action hash = `keccak256(msgpack(action) + nonce + vault_address_byte)`
- Domain stays the same (chainId=1337 testnet, 42161 mainnet via `signature_chain_id` switch)
- Return `{r, s, v}` with `v` as int

### Funding cadence per venue

Add registry: `exchanges.{venue}.funding_intervals_per_year` (numeric):
- `binance: 1095.75` (8h)
- `bybit: 1095.75` (8h, same as Binance USDT-margined)
- `hyperliquid: 8766.0` (1h)

`FundingArbStrategy._open_hedge` reads the per-venue value instead of `strategies.funding_arb.intervals_per_year`. Keep the legacy key as a fallback for `_features` in factor portfolio.

### Realized vol estimator

`backend/app/risk/vol_estimator.py` — `RollingVolEstimator`:
- Records `(ts_ms, close_px)` per symbol
- `annualised_vol(symbol, window_bars=30)` returns sqrt(252*24*60) * stdev_of_log_returns
- Backed by in-memory deque (Phase 8+ pattern)
- `FundingArbStrategy._open_hedge` accepts an injected estimator OR builds one stateless from `state.snapshot.bars` history if available

Simpler approach for HP1: estimator hydrated by the live runner per-tick. Strategy reads via a sidecar dict on `MarketSnapshot` (new field).

Actually simplest: add `MarketSnapshot.realized_vols: dict[tuple[str, str], float]` (default-factory dict). Runner populates from rolling kline history; backtest engine populates from Parquet window. Strategy reads `state.snapshot.realized_vols.get((venue, symbol), 0.6)` (graceful fallback).

### Basis halt

In `FundingArbStrategy._evaluate_one`: when both spot and perp bars are present, compute `basis_bps = abs(perp_close - spot_close) / spot_close * 10_000`. If `basis_bps > strategies.funding_arb.basis_halt_bps` (default 80), return `[]` (skip this symbol). Logs a warning.

## Components

- `backend/app/exchanges/hyperliquid.py` — msgpack signing
- `backend/pyproject.toml` — add `msgpack>=1.0`
- `backend/app/profile/defaults.py` — 3 new venue funding-interval keys
- `backend/app/backtest/state.py` — add `realized_vols` field to `MarketSnapshot`
- `backend/app/risk/vol_estimator.py` — `RollingVolEstimator`
- `backend/app/strategies/funding_arb.py` — read realized_vol from snapshot + basis halt
- `backend/tests/exchanges/test_hyperliquid.py` — verify signature shape changes
- `backend/tests/risk/test_vol_estimator.py` — 3 tests
- `backend/tests/strategies/test_funding_arb.py` — 2 new tests (basis halt + per-venue cadence)

## DoD

~300 tests pass. HL signing uses msgpack. Strategy A respects per-venue funding cadence + basis halt + reads real vol from snapshot.
