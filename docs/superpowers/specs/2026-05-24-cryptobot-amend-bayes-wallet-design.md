# HP11 — Order Amendment + Bayesian Kelly + Backup Wallet Rotation

**Date**: 2026-05-24

## Goal

1. **Order amendment** — `Exchange.amend_order(order_id, new_qty, new_limit_px)` Protocol method; PaperExchange + Binance + Bybit implement. HL doesn't support → raises NotImplementedError.
2. **Bayesian Kelly** — `BayesianKellySizer` that takes a prior + observed returns and updates posterior expected return + posterior variance for Kelly sizing.
3. **Backup wallet rotation** — `WalletRotator` service that picks `{sub_account}_a` vs `{sub_account}_b` based on a registry flag, allowing zero-downtime key swap.

## Components

- `backend/app/exchanges/base.py` — add `amend_order` Protocol method
- `backend/app/exchanges/paper.py` — in-memory amend
- `backend/app/exchanges/binance.py` — `PUT /api/v3/order` cancelReplace
- `backend/app/exchanges/bybit.py` — `/v5/order/amend`
- `backend/app/exchanges/hyperliquid.py` — `NotImplementedError`
- `backend/app/risk/bayesian_kelly.py` — `BayesianKellySizer.update(observed_return)` + `kelly_fraction()` 
- `backend/app/services/wallet_rotator.py` — picks active sub-account name per registry
- Tests for each

## DoD

~344 tests. Amend method on Protocol with paper impl; Bayesian Kelly converges; wallet rotator picks the right sub-account.
