# Cryptobot Hardening Pass 8 — Real WebSocket Fills

**Date**: 2026-05-24

## Goal

Replace the Phase 11 stubs (`NotImplementedError`) in `binance_ws.py`, `bybit_ws.py`, `hyperliquid_ws.py` with real WebSocket clients that subscribe to per-venue user-data streams and emit fill events.

## Architecture

Use `websockets>=12.0` (new dep) — pure-Python WS client compatible with asyncio. Each adapter:
- `connect()` opens the WS, authenticates if required (Binance uses listenKey from REST; Bybit + HL sign auth payload)
- `subscribe(stream)` sends the venue-specific subscribe message
- `iter_messages()` yields parsed JSON dicts
- `next_fill_for(order_id, timeout_s)` consumes until matching `order_id` or timeout
- `close()` shuts down

Reconnection logic in HP8: simple — on disconnect, raise `WSDisconnected`. Caller retries. Real exponential-backoff reconnect = Phase 11+ deeper work.

## Components

- `backend/pyproject.toml` — add `websockets>=12.0`
- `backend/app/exchanges/ws/binance_ws.py` — real impl
- `backend/app/exchanges/ws/bybit_ws.py` — real impl
- `backend/app/exchanges/ws/hyperliquid_ws.py` — real impl
- `backend/tests/exchanges/test_ws_real.py` — mocked-WS tests using a fake server

## DoD

~334 tests pass. Real WS implementations replace stubs. Mocked tests verify message parsing.
