# Cryptobot Phase 11 — WebSocket Fills Design Spec

**Date**: 2026-05-24
**Phase**: 11

## Goal

Replace REST polling for fills with **WebSocket subscriptions** to per-venue user-data streams. Cuts fill-confirmation latency from ~1s (poll interval) to ~50ms. Also feeds real-time mark prices into `LiveStateFetcher` (currently REST-only).

## Architecture

`backend/app/exchanges/ws/` package:
- `base.py` — `WSClient` Protocol: `async connect()`, `async subscribe(stream)`, `async iter_messages() → AsyncIterator[dict]`, `async close()`
- `binance_ws.py` — Binance user-data stream via `wss://stream.binance.com:9443/ws/<listenKey>`
- `bybit_ws.py` — Bybit V5 private channel via `wss://stream.bybit.com/v5/private`
- `hyperliquid_ws.py` — HL `wss://api.hyperliquid.xyz/ws`
- `paper_ws.py` — in-memory queue for tests

`backend/app/oms/service.py` modified: `OMS.dispatch()` accepts optional `ws_client: WSClient | None`. When provided, polling is replaced with `await ws_client.next_fill_for(order_id, timeout=max_fill_wait_s)`.

Phase 11 ships ONLY the Protocol + paper implementation + integration tests with mocked WS. Real WS adapters are stubs with `raise NotImplementedError`; calibration is opt-in via a slow-marker test against real testnet WS endpoints.

## Components

- `app/exchanges/ws/{__init__, base, paper_ws, binance_ws, bybit_ws, hyperliquid_ws}.py`
- `app/oms/service.py` — optional ws_client param
- `tests/exchanges/test_ws_paper.py` — paper WS message flow
- `tests/oms/test_dispatch_ws.py` — OMS dispatch with WS fills

## DoD

~255 tests pass. WSClient Protocol defined + paper impl + 1 OMS test with WS dispatch.
