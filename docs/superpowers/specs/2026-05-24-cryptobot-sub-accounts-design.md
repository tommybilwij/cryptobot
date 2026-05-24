# Cryptobot Phase 13 — Sub-Accounts per Strategy Design Spec

**Date**: 2026-05-24
**Phase**: 13

## Goal

Support **multiple API key pairs per venue** so each strategy runs on its own sub-account. Lets Strategy A (funding arb) and Strategy B (future factor portfolio) trade simultaneously without cross-contamination. Key rotation also becomes per-strategy.

## Architecture

`backend/app/config.py` `Settings` extended with optional `_sub` suffixed keys:
- `binance_api_key_funding_arb` / `..._secret_funding_arb`
- `binance_api_key_factor_pf` / `..._secret_factor_pf`
- ditto for `bybit_*` and `hyperliquid_wallet_private_key_*`

`exchange_factory.build_exchange()` accepts new `sub_account: str | None` kwarg. When provided, reads `{base_field}_{sub_account}` from settings; falls back to base field if sub-key empty.

`live_trade` worker reads `strategies.funding_arb.sub_account` (already in registry, default `"strategy_a_arb"`) and passes through.

## Components

- `backend/app/config.py` — 6 new optional sub-account fields
- `backend/app/services/exchange_factory.py` — `sub_account` param + key resolution
- `backend/app/worker/jobs/live_trade.py` — read sub_account from registry, pass to factory
- `backend/tests/services/test_exchange_factory.py` — 2 new sub-account tests

## DoD

~257 tests pass. Sub-account routing works for Binance (then trivially extends to Bybit/HL by same pattern).
