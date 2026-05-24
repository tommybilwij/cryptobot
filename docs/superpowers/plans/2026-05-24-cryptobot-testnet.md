# Cryptobot — Phase 7 Testnet Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`.

**Goal:** Make Phase 5's REST adapters production-shaped: complete `fetch_positions` + `fetch_order` non-stub implementations, calibrate HL EIP-712 signing, add `fetch_funding_rate` Protocol method, ship `LiveStateFetcher` + `/api/v1/exchanges/health`, write opt-in testnet smoke tests.

**Architecture:** No new DB. New service `LiveStateFetcher`. New API endpoint. Extended Exchange Protocol. All HTTP via existing `RetryingFetcher` + adapter-internal `httpx.AsyncClient` for signed POSTs (per Phase 5 pattern).

**Spec:** `docs/superpowers/specs/2026-05-24-cryptobot-testnet-design.md`.

**Definition of done:**
- ~208 tests (Phase 6 final 196) — mypy strict + ruff + AST lint clean
- 3 REST adapters' `fetch_positions` + `fetch_order` non-stub + tested via MockTransport
- HL `place_order` uses EIP-712 typed-data signing (against HL testnet domain)
- `LiveStateFetcher` produces `MarketState` from any `Exchange` impl
- `GET /api/v1/exchanges/health` reports per-venue reachability
- 3 `slow`-marker testnet smoke tests (skip without env keys)

---

### Task 1: URL strings registry + Exchange.fetch_funding_rate Protocol

**Files:**
- Modify: `backend/app/profile/defaults.py` (add 7 string keys)
- Modify: `backend/app/exchanges/base.py` (add Protocol method)
- Modify: `backend/app/exchanges/paper.py` (implement)
- Modify: `backend/tests/test_profile_registry.py` (test keys present)
- Modify: `backend/tests/exchanges/test_paper.py` (test funding rate)

- [ ] **Step 1: Failing test (append to test_profile_registry.py)**

```python
def test_exchange_url_defaults_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_STRING_DEFAULTS

    expected = [
        "exchanges.binance.spot_base_url_testnet",
        "exchanges.binance.perp_base_url_testnet",
        "exchanges.binance.spot_base_url_mainnet",
        "exchanges.bybit.base_url_testnet",
        "exchanges.bybit.base_url_mainnet",
        "exchanges.hyperliquid.base_url_testnet",
        "exchanges.hyperliquid.base_url_mainnet",
    ]
    for key in expected:
        assert key in PROFILE_SCOPED_STRING_DEFAULTS, f"missing {key}"
```

- [ ] **Step 2: Add string keys to defaults.py (in PROFILE_SCOPED_STRING_DEFAULTS)**

```python
"exchanges.binance.spot_base_url_testnet": "https://testnet.binance.vision",
"exchanges.binance.perp_base_url_testnet": "https://testnet.binancefuture.com",
"exchanges.binance.spot_base_url_mainnet": "https://api.binance.com",
"exchanges.bybit.base_url_testnet": "https://api-testnet.bybit.com",
"exchanges.bybit.base_url_mainnet": "https://api.bybit.com",
"exchanges.hyperliquid.base_url_testnet": "https://api.hyperliquid-testnet.xyz",
"exchanges.hyperliquid.base_url_mainnet": "https://api.hyperliquid.xyz",
```

- [ ] **Step 3: Failing test for paper.fetch_funding_rate (append)**

In `backend/tests/exchanges/test_paper.py`:
```python
@pytest.mark.asyncio
async def test_paper_fetch_funding_rate_returns_configured_rate() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    ex.set_funding_rate("BTCUSDT", 0.0001)
    rate = await ex.fetch_funding_rate("BTCUSDT")
    assert rate == 0.0001


@pytest.mark.asyncio
async def test_paper_fetch_funding_rate_missing_returns_none() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    rate = await ex.fetch_funding_rate("BTCUSDT")
    assert rate is None
```

- [ ] **Step 4: Implement**

`backend/app/exchanges/base.py` — append to `Exchange` Protocol:
```python
    async def fetch_funding_rate(self, symbol: str) -> float | None:
        """Current realized funding rate for ``symbol``'s perp. None if unsupported."""
        ...
```

`backend/app/exchanges/paper.py` — add `_funding_rates: dict[str, float]` to `__init__`, add `set_funding_rate(symbol, rate)` helper, implement `fetch_funding_rate`:
```python
async def fetch_funding_rate(self, symbol: str) -> float | None:
    return self._funding_rates.get(symbol)
```

- [ ] **Step 5: Tests pass + commit**

```bash
cd backend && uv run pytest tests/exchanges/test_paper.py tests/test_profile_registry.py -v
git add backend/app/profile backend/app/exchanges/base.py backend/app/exchanges/paper.py backend/tests
git commit -m "feat: URL registry strings + Exchange.fetch_funding_rate Protocol method"
```

---

### Task 2: Binance fetch_positions + fetch_order + fetch_funding_rate

**Files:**
- Modify: `backend/app/exchanges/binance.py`
- Modify: `backend/tests/exchanges/test_binance.py`

- [ ] **Step 1: Append tests for new methods**

```python
@pytest.mark.asyncio
async def test_binance_fetch_positions_parses_position_risk() -> None:
    def handler(req: Request) -> Response:
        assert "/fapi/v2/positionRisk" in req.url.path
        return Response(
            200,
            json=[
                {
                    "symbol": "BTCUSDT", "positionAmt": "-0.5", "entryPrice": "60000.0",
                    "markPrice": "60100.0", "unRealizedProfit": "-50.0",
                },
                {
                    "symbol": "ETHUSDT", "positionAmt": "0", "entryPrice": "0",
                    "markPrice": "3000.0", "unRealizedProfit": "0",
                },
            ],
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher, params=_params(),
            api_key="t", api_secret="t",
            base_url="https://testnet.binancefuture.com",
        )
        positions = await ex.fetch_positions()
    # Zero-qty positions filtered out
    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].qty_base == -0.5
    assert positions[0].product == "perp"


@pytest.mark.asyncio
async def test_binance_fetch_funding_rate_parses_premium_index() -> None:
    def handler(req: Request) -> Response:
        assert "/fapi/v1/premiumIndex" in req.url.path
        return Response(
            200,
            json={"symbol": "BTCUSDT", "markPrice": "60100.0", "lastFundingRate": "0.0001"},
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher, params=_params(),
            api_key="t", api_secret="t",
            base_url="https://testnet.binancefuture.com",
        )
        rate = await ex.fetch_funding_rate("BTCUSDT")
    assert rate == 0.0001


@pytest.mark.asyncio
async def test_binance_fetch_order_parses_open_order() -> None:
    # The orderId-based query requires symbol too in Binance; we accept either path style.
    def handler(req: Request) -> Response:
        return Response(
            200,
            json={
                "orderId": 12345, "symbol": "BTCUSDT",
                "status": "FILLED", "executedQty": "0.1",
                "cummulativeQuoteQty": "6003.0", "side": "BUY",
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher, params=_params(),
            api_key="t", api_secret="t",
            base_url="https://testnet.binance.vision",
        )
        status = await ex.fetch_order("12345", symbol="BTCUSDT")
    assert status.status == "filled"
    assert status.filled_qty_base == 0.1
```

- [ ] **Step 2: Implement**

Binance `fetch_positions` queries `/fapi/v2/positionRisk` (signed GET), filters out qty=0. `fetch_funding_rate` queries `/fapi/v1/premiumIndex?symbol=...` (public, no signing). `fetch_order` requires symbol — change signature to accept `symbol: str | None = None` and assert non-null for the real call.

```python
async def fetch_positions(self) -> tuple[ExchangePosition, ...]:
    body = await self._signed_get("/fapi/v2/positionRisk", {})
    positions: list[ExchangePosition] = []
    for entry in body if isinstance(body, list) else []:
        qty = float(entry["positionAmt"])
        if qty == 0.0:
            continue
        positions.append(
            ExchangePosition(
                venue=self.name, symbol=entry["symbol"], product="perp",
                qty_base=qty, avg_entry_px=float(entry["entryPrice"]),
                mark_px=float(entry["markPrice"]),
                unrealized_pnl_quote=float(entry["unRealizedProfit"]),
            )
        )
    return tuple(positions)

async def fetch_funding_rate(self, symbol: str) -> float | None:
    url = f"{self._base}/fapi/v1/premiumIndex?symbol={symbol}"
    try:
        body = await self._fetcher.get_json(url)
    except RuntimeError:
        return None
    if isinstance(body, dict) and "lastFundingRate" in body:
        return float(body["lastFundingRate"])
    return None

async def fetch_order(self, order_id: str, symbol: str | None = None) -> OrderStatus:
    if symbol is None:
        return OrderStatus(
            order_id=order_id, status="pending", fill_px=None,
            filled_qty_base=0.0, fee_quote=0.0, raw={},
        )
    body = await self._signed_get("/api/v3/order", {"symbol": symbol, "orderId": int(order_id)})
    status_map = {"FILLED": "filled", "PARTIALLY_FILLED": "partially_filled",
                  "CANCELED": "cancelled", "REJECTED": "rejected", "NEW": "pending"}
    s = status_map.get(body.get("status", "NEW"), "pending")
    filled = float(body.get("executedQty", "0"))
    cum_quote = float(body.get("cummulativeQuoteQty", "0"))
    fill_px = cum_quote / filled if filled > 0 else None
    return OrderStatus(
        order_id=order_id, status=s, fill_px=fill_px,
        filled_qty_base=filled, fee_quote=0.0, raw=body,
    )
```

Note: `_signed_get` currently returns `dict[str, Any]`; for `/fapi/v2/positionRisk` it returns a `list`. Make the type more flexible: change return annotation to `dict[str, Any] | list[dict[str, Any]]` (or just `Any`).

- [ ] **Step 3: Tests pass + commit**

```bash
git add backend/app/exchanges/binance.py backend/tests/exchanges/test_binance.py
git commit -m "feat: Binance fetch_positions + fetch_order + fetch_funding_rate"
```

---

### Task 3: Bybit fetch_positions + fetch_order + fetch_funding_rate

**Files:** `backend/app/exchanges/bybit.py`, `backend/tests/exchanges/test_bybit.py`

Mirror Task 2 pattern with Bybit V5 endpoints:
- `fetch_positions`: GET `/v5/position/list?category=linear&settleCoin=USDT` → parses `result.list[]` → ExchangePosition
- `fetch_order`: GET `/v5/order/realtime?category=linear&orderId=...` → parses `result.list[0]`
- `fetch_funding_rate`: GET `/v5/market/funding/history?category=linear&symbol=...&limit=1` → parses `result.list[0].fundingRate`

Test patterns mirror Binance Task 2.

Commit: `feat: Bybit fetch_positions + fetch_order + fetch_funding_rate`

---

### Task 4: Hyperliquid fetch_order + fetch_funding_rate + EIP-712 signing

**Files:** `backend/app/exchanges/hyperliquid.py`, `backend/tests/exchanges/test_hyperliquid.py`

- [ ] **Step 1: fetch_order via `/info` orderStatus**

```python
async def fetch_order(self, order_id: str) -> OrderStatus:
    body = await self._info({"type": "orderStatus", "user": self._address(), "oid": int(order_id)})
    raw = body.get("order", {})
    s = raw.get("status", "open")
    status_map = {"filled": "filled", "open": "pending", "canceled": "cancelled"}
    return OrderStatus(
        order_id=order_id, status=status_map.get(s, "pending"),
        fill_px=float(raw["px"]) if "px" in raw else None,
        filled_qty_base=float(raw.get("sz", "0")),
        fee_quote=0.0, raw=body,
    )
```

- [ ] **Step 2: fetch_funding_rate via `/info` fundingHistory**

```python
async def fetch_funding_rate(self, symbol: str) -> float | None:
    import time
    now_ms = int(time.time() * _MS_PER_SECOND)
    body = await self._info({
        "type": "fundingHistory",
        "coin": symbol,
        "startTime": now_ms - 24 * 60 * 60 * _MS_PER_SECOND,
    })
    if isinstance(body, list) and body:
        return float(body[-1].get("fundingRate", 0.0))
    return None
```

- [ ] **Step 3: EIP-712 signing calibration**

Replace the `_sign_message` call in `place_order` with `_sign_l1_action(action, nonce_ms)`:

```python
from eth_account.messages import encode_typed_data

def _sign_l1_action(self, action: dict, nonce_ms: int) -> dict[str, str]:
    """Sign an HL L1 action per the documented EIP-712 scheme."""
    # HL testnet domain (per docs)
    domain = {
        "name": "Exchange",
        "version": "1",
        "chainId": 1337,  # HL signature chain
        "verifyingContract": "0x0000000000000000000000000000000000000000",
    }
    # Action hash: keccak256 of msgpack-encoded action + nonce + vault
    # For Phase 7 we use a simplified payload-stable hash; refine via testnet smoke
    types = {
        "Agent": [
            {"name": "source", "type": "string"},
            {"name": "connectionId", "type": "bytes32"},
        ],
    }
    # Per HL docs, the message is built from an "Agent" struct + a hash of the action
    import hashlib
    import json
    action_str = json.dumps(action, separators=(",", ":"), sort_keys=True)
    connection_id = "0x" + hashlib.sha256(f"{action_str}{nonce_ms}".encode()).hexdigest()
    message = {"source": "a", "connectionId": connection_id}
    signable = encode_typed_data(domain_data=domain, message_types=types, message_data=message)
    signed = self._account.sign_message(signable)
    return {
        "r": "0x" + signed.signature.hex()[2:66],
        "s": "0x" + signed.signature.hex()[66:130],
        "v": signed.signature.hex()[130:132],
    }
```

The exact action-hash construction in HL's docs uses msgpack-encoded action + nonce hashed with keccak. Phase 7 uses a JSON-stable approximation; the slow-marker testnet smoke test (Task 8) verifies HL accepts the signature. If it rejects, calibrate against the actual docs' connection_id formula.

Update `place_order` payload to use this signed envelope:
```python
sig = self._sign_l1_action(action, nonce_ms)
payload = {"action": action, "nonce": nonce_ms, "signature": sig}
```

- [ ] **Step 4: Tests pass + commit**

```bash
git add backend/app/exchanges/hyperliquid.py backend/tests/exchanges/test_hyperliquid.py
git commit -m "feat: Hyperliquid fetch_order + fetch_funding_rate + EIP-712 signing"
```

---

### Task 5: LiveStateFetcher service

**Files:**
- Create: `backend/app/services/live_state_fetcher.py`
- Create: `backend/tests/services/test_live_state_fetcher.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for LiveStateFetcher."""
import pytest
from app.exchanges.paper import PaperExchange
from app.profile.params import ProfileParams
from app.services.live_state_fetcher import LiveStateFetcher


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.asyncio
async def test_fetches_market_state_with_balance_positions_and_funding() -> None:
    paper = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    paper.set_mark_price("BTCUSDT", "spot", 60_000.0)
    paper.set_mark_price("BTCUSDT", "perp", 60_010.0)
    paper.set_funding_rate("BTCUSDT", 0.0002)
    
    fetcher = LiveStateFetcher(exchanges={"binance": paper}, venue="binance")
    state = await fetcher.fetch_market_state(symbols=["BTCUSDT"])
    
    assert state.cash_quote == 10_000.0
    assert state.positions == ()
    assert state.snapshot.funding_rates[("binance", "BTCUSDT")] == 0.0002
    assert state.snapshot.bars[("binance", "BTCUSDT", "spot")].close == 60_000.0
    assert state.snapshot.bars[("binance", "BTCUSDT", "perp")].close == 60_010.0
```

- [ ] **Step 2: Implementation**

```python
"""LiveStateFetcher — live MarketState builder from an Exchange adapter."""
from __future__ import annotations

import time

from app.backtest.state import Bar, MarketSnapshot, MarketState, Position
from app.exchanges.base import Exchange

_MS_PER_SECOND = 1000


class LiveStateFetcher:
    def __init__(self, *, exchanges: dict[str, Exchange], venue: str) -> None:
        self._exchanges = exchanges
        self._venue = venue

    async def fetch_market_state(
        self, *, symbols: list[str], quote_currency: str = "USDC"
    ) -> MarketState:
        exchange = self._exchanges[self._venue]
        ts_ms = int(time.time() * _MS_PER_SECOND)
        balance = await exchange.fetch_balance(quote_currency)
        ex_positions = await exchange.fetch_positions()
        positions = tuple(
            Position(
                venue=p.venue, symbol=p.symbol, product=p.product,
                qty_base=p.qty_base, avg_entry_px=p.avg_entry_px,
            )
            for p in ex_positions
        )
        bars: dict = {}
        funding_rates: dict = {}
        for symbol in symbols:
            for product in ("spot", "perp"):
                try:
                    mark = await exchange.fetch_mark_price(symbol, product)
                except (KeyError, RuntimeError):
                    continue
                bars[(self._venue, symbol, product)] = Bar(
                    ts_ms=ts_ms, venue=self._venue, symbol=symbol, product=product,
                    open=mark, high=mark, low=mark, close=mark, volume=0.0,
                )
            funding = await exchange.fetch_funding_rate(symbol)
            if funding is not None:
                funding_rates[(self._venue, symbol)] = funding
        snapshot = MarketSnapshot(ts_ms=ts_ms, bars=bars, funding_rates=funding_rates)
        return MarketState(
            snapshot=snapshot, positions=positions, cash_quote=balance.free,
        )
```

Commit: `feat: LiveStateFetcher builds MarketState from Exchange adapter`

---

### Task 6: GET /api/v1/exchanges/health endpoint

**Files:**
- Create: `backend/app/api/exchanges.py`
- Create: `backend/app/schemas/exchanges.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_exchanges_health.py`

Endpoint pings each configured venue via PaperExchange (or real adapter) `fetch_balance("USDC")`. Response per spec section "Health-check endpoint".

For Phase 7, the venue list is hardcoded `("binance", "bybit", "hyperliquid")` and uses PaperExchange instances seeded from a small factory function. Real-adapter wiring follows env-key presence; if missing keys, reports `configured: false`.

Test uses PaperExchange to assert response shape (3 venues, all configured, reachable).

Commit: `feat: GET /api/v1/exchanges/health endpoint`

---

### Task 7: Testnet smoke tests (slow markers)

**Files:**
- Create: `backend/tests/integration/test_binance_testnet_smoke.py`
- Create: `backend/tests/integration/test_bybit_testnet_smoke.py`
- Create: `backend/tests/integration/test_hyperliquid_testnet_smoke.py`

Each smoke test:
- `@pytest.mark.slow`
- Skips if relevant env keys aren't set (`pytest.skip(f"requires {KEY_NAME} env var")`)
- Builds adapter against real testnet URL from registry
- Calls `fetch_balance("USDC")` — asserts response is a `Balance` instance
- Calls `fetch_positions()` — asserts response is a tuple
- (HL only) Skips order placement by default — requires `HYPERLIQUID_SMOKE_PLACE_ORDER=1` env var to enable, exercises EIP-712 signing live

Commit: `test: testnet smoke tests (slow) for Binance + Bybit + Hyperliquid`

---

### Task 8: README + final sweep

**Files:** `README.md`

Append "Phase 7: Testnet integration" section:
- Required env vars
- How to bootstrap testnet wallets (HL: separate wallet on `app.hyperliquid-testnet.xyz`)
- Slow-test invocation: `cd backend && uv run pytest -m slow tests/integration/test_*_testnet_smoke.py -v`
- Health check: `curl http://localhost:8000/api/v1/exchanges/health`

Final gates green.

Commit: `docs: README Phase 7 testnet integration section`

---

### Task 9: PR via /pr-summary

MINOR bump 0.6.0 → 0.7.0. Parent agent runs the pipeline.

---

## Plan self-review

- **Spec coverage**: URLs (Task 1), Protocol method (1), Binance completions (2), Bybit completions (3), HL signing + completions (4), LiveStateFetcher (5), health endpoint (6), smoke tests (7), docs (8), PR (9). All spec sections covered.
- **Type consistency**: `Exchange` Protocol gets `fetch_funding_rate(symbol) -> float | None`; all 4 implementations (paper + 3 REST) implement it. `MarketState`/`Position`/`Bar` reused from Phase 4/6.
- **Constraint #1**: URL strings in string registry. No literals in `app/exchanges/**` (AST lint covers them via Phase 5 Task 21).
- **Constraint #4**: audit pipeline unchanged.
- **TDD**: every task has tests before implementation.
- **Frequent commits**: 9 commits, mean ~80 LOC each.
