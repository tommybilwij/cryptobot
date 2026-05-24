# Cryptobot Phase 7 — Testnet Integration Design Spec

**Date**: 2026-05-24
**Status**: approved (autonomous mode)
**Phase**: 7 of the cryptobot build
**Blocks**: Phase 8 (dry-run), Phase 9 (live $500)
**Revision history**: v1 — initial. PR #<fill-in-after-merge>.

## Goal

Validate the Phase 5 adapter layer against **real Binance, Bybit, and Hyperliquid testnet endpoints**, finish the stubbed methods (`fetch_positions`, `fetch_order`), calibrate Hyperliquid's EIP-712 signing, and build the **`LiveStateFetcher`** — the live analogue of Phase 6's `BacktestLoader` that produces `MarketState` from real exchange queries.

## Non-goals

- **Live runner loop (`WORKER_JOB=live_trade`)** → Phase 8. Phase 7 builds the *building blocks* live trading needs (real adapters + state fetcher + health checks). The loop that ties strategy → OMS → adapter together in a continuous cycle is Phase 8.
- **WebSocket fills** → Phase 9+. REST polling is fine for funding-arb 1m cadence.
- **Mainnet** → Phase 9.
- **$500 live trade** → Phase 9.

## Architecture

Three building blocks ship in Phase 7, all behind opt-in env / slow-marker gating:

### 1. Adapter completions

The Phase 5 stubs in `fetch_positions` and `fetch_order` get real implementations:
- **Binance**: `/api/v3/openOrders?symbol=...` for spot orders; `/fapi/v2/positionRisk` for perp positions; `/api/v3/account` already complete for balances.
- **Bybit**: `/v5/position/list?category=linear` for perp positions; `/v5/order/realtime?category=...&orderId=...` for fetch_order.
- **Hyperliquid**: `clearinghouseState` already returns `assetPositions` — extend the parser. `orderStatus` query for `fetch_order`.

The HL adapter's `place_order` currently signs with EIP-191 personal-sign over `address+nonce`. Phase 7 calibrates this to HL's real EIP-712 typed-data scheme by:
- Encoding the action as JSON per HL's docs
- Building the EIP-712 domain `{name: "Exchange", version: "1", chainId: 1337, verifyingContract: 0x...}` per HL testnet
- Signing the typed-data hash with the wallet key

The calibration uses **real testnet response shapes** as the ground truth — a slow-marker smoke test posts an order and verifies HL's `status: "ok"` response.

### 2. LiveStateFetcher service

`backend/app/services/live_state_fetcher.py`:

```python
class LiveStateFetcher:
    def __init__(self, *, exchanges: dict[str, Exchange], venue: str) -> None: ...
    
    async def fetch_market_state(
        self, *, symbols: list[str], quote_currency: str = "USDC"
    ) -> MarketState: ...
```

Returns a `MarketState` populated from:
- `Exchange.fetch_balance(quote_currency)` → `cash_quote`
- `Exchange.fetch_positions()` → converted to `tuple[Position, ...]`
- `Exchange.fetch_mark_price(symbol, product)` for each (symbol, product) → builds `Bar` (close=mark, OHLV all = mark since live tick has no historical bar)
- `Exchange.fetch_funding_rate(symbol)` (new Protocol method) → `funding_rates` dict

New `Exchange.fetch_funding_rate(symbol) -> float | None` Protocol method. Phase 5 paper + 3 REST adapters all implement.

### 3. Health-check endpoint

`GET /api/v1/exchanges/health`:
```json
{
  "venues": [
    {"name": "binance", "configured": true, "use_testnet": true, "reachable": true, "balance_quote": 10000.0, "error": null},
    {"name": "bybit", "configured": true, "use_testnet": true, "reachable": false, "balance_quote": null, "error": "AuthFailed: ..."}
  ]
}
```

Each venue is pinged via `fetch_balance("USDC")` — non-destructive, low rate-limit cost. Used by the future Strategy Lab UI to surface adapter status.

### 4. Slow-marker smoke tests

`backend/tests/integration/test_{venue}_testnet_smoke.py` — three new files, all `@pytest.mark.slow`. Each:
- Skips if the relevant API keys aren't in env
- Calls `fetch_balance` against real testnet → assert response shape
- Fetches positions / open orders → assert response shape
- (Hyperliquid only) places a tiny test order + cancels — exercises the EIP-712 signing path

These tests are opt-in (`uv run pytest -m slow`), require real testnet keys, and are NOT run in CI.

## Components

```
app/exchanges/binance.py        # MODIFY: complete fetch_positions + fetch_order
app/exchanges/bybit.py          # MODIFY: complete fetch_positions + fetch_order  
app/exchanges/hyperliquid.py    # MODIFY: complete fetch_order + EIP-712 signing
app/exchanges/base.py           # MODIFY: add fetch_funding_rate Protocol method
app/exchanges/paper.py          # MODIFY: implement fetch_funding_rate (returns configured rate)
app/services/live_state_fetcher.py   # NEW
app/api/exchanges.py            # NEW: GET /api/v1/exchanges/health
app/schemas/exchanges.py        # NEW: Pydantic response model
app/main.py                     # MODIFY: register exchanges router
tests/integration/test_binance_testnet_smoke.py    # NEW (slow)
tests/integration/test_bybit_testnet_smoke.py      # NEW (slow)
tests/integration/test_hyperliquid_testnet_smoke.py # NEW (slow)
tests/services/test_live_state_fetcher.py          # NEW (uses PaperExchange)
tests/api/test_exchanges_health.py                 # NEW
tests/exchanges/test_binance.py                    # MODIFY: add fetch_positions + fetch_order tests
tests/exchanges/test_bybit.py                      # MODIFY: same
tests/exchanges/test_hyperliquid.py                # MODIFY: same
```

## Profile registry additions

Numeric (`PROFILE_SCOPED_DEFAULTS`):
```
exchanges.binance.spot_base_url_testnet      "https://testnet.binance.vision"      (STRING)
exchanges.binance.perp_base_url_testnet      "https://testnet.binancefuture.com"   (STRING)
exchanges.bybit.base_url_testnet             "https://api-testnet.bybit.com"       (STRING)
exchanges.hyperliquid.base_url_testnet       "https://api.hyperliquid-testnet.xyz" (STRING)
exchanges.binance.spot_base_url_mainnet      "https://api.binance.com"             (STRING)
exchanges.bybit.base_url_mainnet             "https://api.bybit.com"               (STRING)
exchanges.hyperliquid.base_url_mainnet       "https://api.hyperliquid.xyz"         (STRING)
```

These are all strings, so they go in `PROFILE_SCOPED_STRING_DEFAULTS`.

Adapter factories read `exchanges.{venue}.use_testnet` (from BOOL registry, Phase 5) and choose the appropriate URL.

## Database / migrations

**None.** Phase 7 doesn't touch persistence — it only fleshes out the live integration layer.

## Testing strategy

~12 new tests:
- 3 mocked-HTTP tests per adapter for `fetch_positions` + `fetch_order` (6 total across Binance + Bybit)
- 2 HL-specific tests: signing fixture + `fetch_order`
- 1 PaperExchange `fetch_funding_rate` test
- 1 `LiveStateFetcher` test (uses PaperExchange to build a MarketState)
- 1 `/api/v1/exchanges/health` test (uses PaperExchange across configured venues)
- 3 slow-marker testnet smoke tests (skip without env keys)

## Edge cases

- **Missing env keys** → adapter factory returns `None`, health check reports `configured: false`
- **Network failure on health check** → `reachable: false` + error message; doesn't fail the whole response
- **HL signing mismatch** → `AuthFailed` raised; calibrate against the actual `signature_chain_id` and domain in HL testnet docs
- **`fetch_funding_rate` returns None** → strategy sees `None` in `funding_rates` dict → no-op (already handled in Phase 6 FundingArb)
- **Empty positions response** → returns `()` (already handled in Phase 5 stubs)

## Definition of done (gate to Phase 8)

- ~208 tests pass (Phase 6 final 196) — mypy --strict + ruff + AST lint clean
- All 3 REST adapters have `fetch_positions` and `fetch_order` non-stub implementations
- HL `place_order` signs with EIP-712 typed-data (calibrated against testnet)
- `LiveStateFetcher` produces a `MarketState` from any `Exchange` implementation
- `GET /api/v1/exchanges/health` returns venue reachability
- 3 slow-marker testnet smoke tests written (skip cleanly without env keys)
- README "Phase 7: Testnet integration" section with: required env vars, slow-test invocation, testnet wallet bootstrap (HL especially)

## Out of scope (deferred)

- Live runner loop (continuous strategy → OMS → exchange) → Phase 8
- Mainnet → Phase 9
- WebSocket fills → Phase 9+
- $500 live trade → Phase 9

## References

- `docs/superpowers/specs/2026-05-24-cryptobot-oms-design.md` — Phase 5 adapter layer
- `docs/superpowers/specs/2026-05-24-cryptobot-strategy-a-design.md` — Phase 6 strategy that depends on this
- `backend/app/exchanges/{binance,bybit,hyperliquid}.py` — current Phase 5 stubs
- Hyperliquid signing reference: <https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint>
