# HP10 — WS Integration + Listen-Key Refresh + Load Harness

**Date**: 2026-05-24

## Goal

1. **Wire WSClient into OMS** — when `ws_client` is provided, OMS uses `next_fill_for` instead of REST polling
2. **Binance listen-key refresh loop** — 30-min cadence keepalive PUT
3. **Load test harness** — a `just load-test` recipe that runs N concurrent backtest jobs

## Components

- `backend/app/oms/service.py` — `_poll_until_terminal` checks optional `ws_client` first
- `backend/app/exchanges/ws/binance_listen_key.py` — `ListenKeyKeepalive` async task
- `backend/tests/load/test_concurrent_backtests.py` — slow-marker concurrent test
- `justfile` — `load-test` recipe

## DoD

~340 tests. WS path opt-in via OMS constructor.
