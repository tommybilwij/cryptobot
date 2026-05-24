# Cryptobot — Phase 5 OMS + Exchange Adapters + Decision Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the exchange-facing infrastructure: a uniform `Exchange` Protocol with REST adapters for Binance, Bybit, and Hyperliquid; an OMS service that dispatches `list[Order]` from `Strategy.evaluate()` with kill switch + reconciliation; a `DecisionAuditEntry` log capturing every order-producing decision (Constraint #4).

**Architecture:** Three layered concerns: (1) `app/exchanges/` Protocol + 4 implementations (paper + 3 REST); (2) `app/oms/` service that bridges backtest-shape `Order` dataclasses to live execution with halt-class drift detection; (3) `app/services/decision_audit.py` audit ORM + service. All HTTP via `httpx` + Phase 3's `RetryingFetcher` (extended for POST/JSON). No real network calls in tests — `httpx.MockTransport` only. Testnet integration is Phase 7.

**Tech Stack:** Python 3.12+, httpx, eth_account (NEW for Hyperliquid EIP-712), SQLAlchemy 2.x async, FastAPI, Pydantic v2, Alembic, pytest + pytest-asyncio. All existing except eth_account.

**Scope:** Phase 5 only. Spec: `docs/superpowers/specs/2026-05-24-cryptobot-oms-design.md`. Blocks Phase 6 (Strategy A), Phase 7 (testnet integration), Phase 8 (dry-run), Phase 9 (live $500).

**Definition of done (gate to Phase 6):**
- ~135 tests total (Phase 4 final: 122) — mypy --strict + ruff + AST lint clean
- All 4 adapter unit tests pass against MockTransport
- OMS happy-path test: 2-leg hedge pair dispatch succeeds end-to-end with paper adapter; one `DecisionAuditEntry` written
- Kill switch flag halts dispatch, audit entry logged with `reconciliation_status="kill_switch"`
- Hedge drift > 5% → `HedgeDriftHalt`; book drift > 2% → `ReconciliationDriftHalt`
- `POST /api/v1/oms/kill` flips flag + creates new profile version
- Alembic migration `0004_create_decision_audit_entries` applies + reverses cleanly
- No numeric/boolean literals in `backend/app/oms/**` or `backend/app/exchanges/**` (AST lint enforced)
- New `PROFILE_SCOPED_BOOL_DEFAULTS` registry working alongside the existing three

---

## Phase 5.1: Registry + dataclass foundations

### Task 1: Profile registry — BOOL registry + OMS/exchanges keys

**Files:**
- Modify: `backend/app/profile/defaults.py`
- Modify: `backend/app/profile/params.py`
- Modify: `backend/tests/test_profile_registry.py`
- Modify: `backend/pyproject.toml` (add `eth_account` dep)

- [ ] **Step 1: Add eth_account dep**

```bash
cd backend && uv add 'eth-account>=0.13'
```

- [ ] **Step 2: Failing tests (append to `backend/tests/test_profile_registry.py`)**

```python
def test_bool_defaults_registry_exists() -> None:
    from app.profile.defaults import PROFILE_SCOPED_BOOL_DEFAULTS

    assert isinstance(PROFILE_SCOPED_BOOL_DEFAULTS, dict)


def test_oms_kill_switch_default_false() -> None:
    from app.profile.defaults import PROFILE_SCOPED_BOOL_DEFAULTS

    assert PROFILE_SCOPED_BOOL_DEFAULTS["oms.kill_switch_active"] is False


def test_oms_drift_thresholds_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    assert PROFILE_SCOPED_DEFAULTS["oms.hedge_drift_halt_pct"] == 0.05
    assert PROFILE_SCOPED_DEFAULTS["oms.reconcile_drift_halt_pct"] == 0.02
    assert PROFILE_SCOPED_DEFAULTS["oms.fill_poll_interval_s"] == 1.0
    assert PROFILE_SCOPED_DEFAULTS["oms.max_fill_wait_s"] == 30.0
    assert PROFILE_SCOPED_DEFAULTS["oms.audit_snapshot_interval_s"] == 3600


def test_exchange_testnet_defaults_true() -> None:
    from app.profile.defaults import PROFILE_SCOPED_BOOL_DEFAULTS

    for venue in ("binance", "bybit", "hyperliquid"):
        assert PROFILE_SCOPED_BOOL_DEFAULTS[f"exchanges.{venue}.use_testnet"] is True


def test_exchange_timeout_defaults_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    for venue in ("binance", "bybit", "hyperliquid"):
        assert PROFILE_SCOPED_DEFAULTS[f"exchanges.{venue}.timeout_s"] == 10.0


def test_profile_params_resolves_bool_default() -> None:
    from app.profile.params import ProfileParams

    p = ProfileParams(profile={})
    assert p.get("oms.kill_switch_active") is False


def test_profile_params_bool_override() -> None:
    from app.profile.params import ProfileParams

    p = ProfileParams(profile={"oms": {"kill_switch_active": True}})
    assert p.get("oms.kill_switch_active") is True
```

- [ ] **Step 3: Add `PROFILE_SCOPED_BOOL_DEFAULTS` + new keys to `backend/app/profile/defaults.py`**

```python
# ... after the existing _DICT_ registry, add:

PROFILE_SCOPED_BOOL_DEFAULTS: dict[str, bool] = {
    # --- OMS kill switch ---
    "oms.kill_switch_active": False,
    # --- Per-venue testnet/mainnet toggle ---
    "exchanges.binance.use_testnet": True,
    "exchanges.bybit.use_testnet": True,
    "exchanges.hyperliquid.use_testnet": True,
}
```

Add to existing NUMERIC `PROFILE_SCOPED_DEFAULTS` dict:
```python
# --- OMS thresholds + cadence ---
"oms.hedge_drift_halt_pct": 0.05,
"oms.reconcile_drift_halt_pct": 0.02,
"oms.fill_poll_interval_s": 1.0,
"oms.max_fill_wait_s": 30.0,
"oms.audit_snapshot_interval_s": 3600,
# --- Exchange timeouts ---
"exchanges.binance.timeout_s": 10.0,
"exchanges.bybit.timeout_s": 10.0,
"exchanges.hyperliquid.timeout_s": 10.0,
```

Extend the `all_profile_keys()` helper to include the bool registry:
```python
def all_profile_keys() -> set[str]:
    return (
        set(PROFILE_SCOPED_DEFAULTS)
        | set(PROFILE_SCOPED_STRING_DEFAULTS)
        | set(PROFILE_SCOPED_DICT_DEFAULTS)
        | set(PROFILE_SCOPED_BOOL_DEFAULTS)
    )
```

- [ ] **Step 4: Extend `ProfileParams.get()` in `backend/app/profile/params.py`**

```python
from app.profile.defaults import (
    PROFILE_SCOPED_BOOL_DEFAULTS,
    PROFILE_SCOPED_DEFAULTS,
    PROFILE_SCOPED_DICT_DEFAULTS,
    PROFILE_SCOPED_STRING_DEFAULTS,
    all_profile_keys,
)

# In ProfileParams.get(), after the existing dict registry check, add:
        if path in PROFILE_SCOPED_BOOL_DEFAULTS:
            return PROFILE_SCOPED_BOOL_DEFAULTS[path]
```

And update the error message:
```python
        raise UnknownParamPath(
            f"path {path!r} is not in PROFILE_SCOPED_DEFAULTS, _STRING_, _DICT_, or _BOOL_"
        )
```

Update existing `_walk` so booleans returned from the profile JSONB still come back as bool (currently fine; bools are valid JSON).

- [ ] **Step 5: Tests pass**

```bash
cd backend && uv run pytest tests/test_profile_registry.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/profile backend/tests/test_profile_registry.py backend/pyproject.toml backend/uv.lock
git commit -m "feat: bool registry + OMS/exchange profile keys + eth_account dep"
```

---

### Task 2: Exchange dataclasses (Balance, ExchangePosition, OrderReceipt, OrderStatus)

**Files:**
- Create: `backend/app/exchanges/__init__.py`
- Create: `backend/app/exchanges/types.py`
- Create: `backend/tests/exchanges/__init__.py`
- Create: `backend/tests/exchanges/test_types.py`

- [ ] **Step 1: Failing test**

`backend/tests/exchanges/test_types.py`:
```python
"""Tests for exchange dataclasses."""

from __future__ import annotations

import pytest

from app.exchanges.types import Balance, ExchangePosition, OrderReceipt, OrderStatus


def test_balance_is_frozen() -> None:
    b = Balance(venue="binance", quote_currency="USDC", free=10000.0, locked=0.0)
    with pytest.raises(Exception):
        b.free = 99.0  # type: ignore[misc]


def test_exchange_position_signed_qty() -> None:
    p = ExchangePosition(
        venue="binance", symbol="BTCUSDT", product="perp",
        qty_base=-0.5, avg_entry_px=60000.0, mark_px=60050.0,
        unrealized_pnl_quote=-25.0,
    )
    assert p.qty_base < 0


def test_order_receipt_carries_id() -> None:
    r = OrderReceipt(order_id="abc-1", venue="binance", symbol="BTCUSDT", submitted_ts_ms=1)
    assert r.order_id == "abc-1"


def test_order_status_filled_carries_fill_px() -> None:
    s = OrderStatus(
        order_id="abc-1", status="filled", fill_px=60010.0,
        filled_qty_base=0.1, fee_quote=0.6, raw={},
    )
    assert s.status == "filled"
    assert s.fill_px == 60010.0


def test_order_status_pending_has_no_fill_px() -> None:
    s = OrderStatus(
        order_id="abc-1", status="pending", fill_px=None,
        filled_qty_base=0.0, fee_quote=0.0, raw={},
    )
    assert s.fill_px is None
```

- [ ] **Step 2: Verify FAILS (ImportError)**

- [ ] **Step 3: Implementation**

`backend/app/exchanges/__init__.py`:
```python
"""Exchange adapter layer.

Implementations satisfy the ``Exchange`` Protocol in ``base.py``. Each adapter
owns one venue's quirks (URLs, auth, response shape); the OMS only sees the
Protocol.
"""
```

`backend/app/exchanges/types.py`:
```python
"""Frozen dataclasses returned by Exchange adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.backtest.state import Product


@dataclass(frozen=True)
class Balance:
    venue: str
    quote_currency: str
    free: float
    locked: float


@dataclass(frozen=True)
class ExchangePosition:
    venue: str
    symbol: str
    product: Product
    qty_base: float
    avg_entry_px: float
    mark_px: float
    unrealized_pnl_quote: float


@dataclass(frozen=True)
class OrderReceipt:
    order_id: str
    venue: str
    symbol: str
    submitted_ts_ms: int


_OrderStatusLiteral = Literal[
    "pending", "filled", "partially_filled", "cancelled", "rejected"
]


@dataclass(frozen=True)
class OrderStatus:
    order_id: str
    status: _OrderStatusLiteral
    fill_px: float | None
    filled_qty_base: float
    fee_quote: float
    raw: dict[str, Any]
```

`backend/tests/exchanges/__init__.py`: empty.

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/exchanges/test_types.py -v
git add backend/app/exchanges backend/tests/exchanges
git commit -m "feat: exchange dataclasses (Balance, ExchangePosition, OrderReceipt, OrderStatus)"
```

---

### Task 3: Exchange Protocol + ExchangeError hierarchy

**Files:**
- Create: `backend/app/exchanges/base.py`
- Create: `backend/app/exchanges/errors.py`

- [ ] **Step 1: Implementation (no test — Protocol is structurally satisfied)**

`backend/app/exchanges/errors.py`:
```python
"""ExchangeError hierarchy — uniform error mapping across venues."""

from __future__ import annotations


class ExchangeError(RuntimeError):
    """Base class for all exchange-side errors."""


class RateLimited(ExchangeError):
    """HTTP 429 or venue-specific rate-limit response."""


class Rejected(ExchangeError):
    """Order rejected (validation, insufficient margin, etc.). HTTP 4xx."""


class Timeout(ExchangeError):
    """No response within timeout window."""


class AuthFailed(ExchangeError):
    """HTTP 401/403 — bad keys or signature mismatch. CRITICAL: halt trading."""


class UnconfiguredVenue(ExchangeError):
    """Profile asked for a venue that isn't configured."""
```

`backend/app/exchanges/base.py`:
```python
"""Exchange Protocol — common interface for live + paper adapters."""

from __future__ import annotations

from typing import Protocol

from app.backtest.orders import Order
from app.backtest.state import Product
from app.exchanges.types import (
    Balance,
    ExchangePosition,
    OrderReceipt,
    OrderStatus,
)


class Exchange(Protocol):
    """One implementation per venue (or PaperExchange for tests + dry-run)."""

    name: str

    async def fetch_balance(self, quote_currency: str) -> Balance:
        """Return free + locked balance of ``quote_currency`` at the venue."""
        ...

    async def fetch_positions(self) -> tuple[ExchangePosition, ...]:
        """Return all open positions across spot + perp on this venue."""
        ...

    async def place_order(self, order: Order) -> OrderReceipt:
        """Submit ``order``. Returns receipt with the venue-assigned ``order_id``.

        Does NOT wait for fill. Caller polls ``fetch_order`` until terminal status.
        """
        ...

    async def fetch_order(self, order_id: str) -> OrderStatus:
        """Get current status of an order placed via ``place_order``."""
        ...

    async def cancel_order(self, order_id: str) -> None:
        """Best-effort cancel. No-op if already filled/cancelled."""
        ...

    async def fetch_mark_price(self, symbol: str, product: Product) -> float:
        """Current mark / index / last-price for the (symbol, product) pair."""
        ...
```

- [ ] **Step 2: Gates green** (no new tests; just lint/typecheck)

```bash
just typecheck && just lint && just test
```
Expected: prior 122 tests still pass; mypy clean (+2 source files); ruff clean.

- [ ] **Step 3: Commit**

```bash
git add backend/app/exchanges/base.py backend/app/exchanges/errors.py
git commit -m "feat: Exchange Protocol + ExchangeError hierarchy"
```

---

## Phase 5.2: Settings + HTTP plumbing

### Task 4: Settings extension for exchange API keys

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/tests/conftest.py` (if needed, to seed test env)

- [ ] **Step 1: Read existing `backend/app/config.py`**

Understand the existing `Settings` class shape (likely pydantic-settings BaseSettings reading from env + `.env`).

- [ ] **Step 2: Add exchange-key fields**

In the `Settings` class, append:
```python
    # --- Exchange API keys (env-only, never in DB) ---
    binance_api_key: str = ""
    binance_api_secret: str = ""
    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    hyperliquid_wallet_private_key: str = ""
```

Empty-string defaults so tests + dev work without configured keys.

- [ ] **Step 3: Failing test (`backend/tests/test_config.py` — create if absent)**

```python
"""Tests for Settings exchange-key fields."""

from __future__ import annotations

from app.config import Settings


def test_binance_keys_default_empty() -> None:
    s = Settings(_env_file=None)
    assert s.binance_api_key == ""
    assert s.binance_api_secret == ""


def test_bybit_keys_default_empty() -> None:
    s = Settings(_env_file=None)
    assert s.bybit_api_key == ""
    assert s.bybit_api_secret == ""


def test_hyperliquid_key_default_empty() -> None:
    s = Settings(_env_file=None)
    assert s.hyperliquid_wallet_private_key == ""


def test_keys_from_env(monkeypatch: "pytest.MonkeyPatch") -> None:  # type: ignore[name-defined]
    monkeypatch.setenv("BINANCE_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "test-secret")
    s = Settings(_env_file=None)
    assert s.binance_api_key == "test-key"
    assert s.binance_api_secret == "test-secret"
```

(Add `import pytest` at the top.)

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/test_config.py -v
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat: Settings exchange API key fields (env-only)"
```

---

### Task 5: Extend RetryingFetcher for POST + JSON

**Files:**
- Modify: `backend/app/market_data/_http.py`
- Modify: `backend/tests/market_data/test_http.py` (append tests)

- [ ] **Step 1: Failing tests (append)**

```python
@pytest.mark.asyncio
async def test_fetcher_get_json_returns_dict() -> None:
    def handler(req: Request) -> Response:
        return Response(200, json={"hello": "world"})

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=3, base_backoff_s=0.0)
        body = await fetcher.get_json("https://example.com/data")
    assert body == {"hello": "world"}


@pytest.mark.asyncio
async def test_fetcher_post_json_sends_body_and_returns_response() -> None:
    def handler(req: Request) -> Response:
        assert req.method == "POST"
        import json
        assert json.loads(req.content) == {"foo": "bar"}
        return Response(200, json={"ok": True})

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=3, base_backoff_s=0.0)
        body = await fetcher.post_json("https://example.com/place", body={"foo": "bar"})
    assert body == {"ok": True}


@pytest.mark.asyncio
async def test_fetcher_post_passes_headers() -> None:
    def handler(req: Request) -> Response:
        assert req.headers.get("X-API-KEY") == "abc"
        return Response(200, json={})

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, base_backoff_s=0.0)
        await fetcher.post_json(
            "https://example.com/place",
            body={"x": 1},
            headers={"X-API-KEY": "abc"},
        )
```

- [ ] **Step 2: Implement (extend `backend/app/market_data/_http.py`)**

Add methods to the existing `RetryingFetcher` class:

```python
    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object] | list[object]:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.get(
                    url, params=params, headers=headers, timeout=30.0
                )
                if resp.status_code == _HTTP_NOT_FOUND:
                    raise FileNotFoundError(url)
                if resp.status_code == _HTTP_OK:
                    return resp.json()
                last_exc = RuntimeError(
                    f"HTTP {resp.status_code} on {url}: {resp.text[:200]}"
                )
            except RequestError as e:
                last_exc = e
            except HTTPStatusError as e:
                last_exc = e

            if attempt < self._max_retries:
                await asyncio.sleep(self._base * (2**attempt))
        raise RuntimeError(f"max retries exceeded for {url}: {last_exc}")

    async def post_json(
        self,
        url: str,
        *,
        body: dict[str, object],
        headers: dict[str, str] | None = None,
    ) -> dict[str, object] | list[object]:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.post(
                    url, json=body, headers=headers, timeout=30.0
                )
                if resp.status_code in (_HTTP_OK, _HTTP_CREATED):
                    return resp.json()
                last_exc = RuntimeError(
                    f"HTTP {resp.status_code} on POST {url}: {resp.text[:200]}"
                )
            except RequestError as e:
                last_exc = e
            except HTTPStatusError as e:
                last_exc = e

            if attempt < self._max_retries:
                await asyncio.sleep(self._base * (2**attempt))
        raise RuntimeError(f"max retries exceeded for POST {url}: {last_exc}")
```

Add `_HTTP_CREATED = 201` at the module level alongside the existing constants.

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/market_data/test_http.py -v
git add backend/app/market_data/_http.py backend/tests/market_data/test_http.py
git commit -m "feat: RetryingFetcher supports get_json + post_json"
```

---

## Phase 5.3: Adapter implementations

### Task 6: PaperExchange adapter

**Files:**
- Create: `backend/app/exchanges/paper.py`
- Create: `backend/tests/exchanges/test_paper.py`

- [ ] **Step 1: Failing test**

`backend/tests/exchanges/test_paper.py`:
```python
"""Tests for PaperExchange — in-memory state machine for unit tests + dry-run."""

from __future__ import annotations

import pytest

from app.backtest.orders import Order
from app.exchanges.paper import PaperExchange
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.asyncio
async def test_paper_fetch_balance_starts_at_initial_cash() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    b = await ex.fetch_balance("USDC")
    assert b.free == 10_000.0
    assert b.locked == 0.0


@pytest.mark.asyncio
async def test_paper_place_buy_fills_at_mark_with_slippage() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    ex.set_mark_price("BTCUSDT", "spot", 60000.0)
    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot",
        side="buy", qty_base=0.1, order_type="market",
    )
    receipt = await ex.place_order(order)
    assert receipt.order_id
    status = await ex.fetch_order(receipt.order_id)
    assert status.status == "filled"
    # 5 bps slippage on default Binance config → 60030
    assert status.fill_px == pytest.approx(60030.0)
    assert status.filled_qty_base == 0.1
    # 10 bps fee on spot
    assert status.fee_quote == pytest.approx(6.003, rel=1e-4)


@pytest.mark.asyncio
async def test_paper_fill_debits_balance() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    ex.set_mark_price("BTCUSDT", "spot", 60000.0)
    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot",
        side="buy", qty_base=0.1, order_type="market",
    )
    await ex.place_order(order)
    b = await ex.fetch_balance("USDC")
    # notional 0.1 * 60030 = 6003 + fee 6.003 = 6009.003
    assert b.free == pytest.approx(10_000.0 - 6009.003, rel=1e-4)


@pytest.mark.asyncio
async def test_paper_fetch_positions_after_buy() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    ex.set_mark_price("BTCUSDT", "spot", 60000.0)
    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot",
        side="buy", qty_base=0.1, order_type="market",
    )
    await ex.place_order(order)
    positions = await ex.fetch_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].qty_base == 0.1


@pytest.mark.asyncio
async def test_paper_cancel_pending_is_noop_for_market_fills() -> None:
    ex = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    ex.set_mark_price("BTCUSDT", "spot", 60000.0)
    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot",
        side="buy", qty_base=0.1, order_type="market",
    )
    receipt = await ex.place_order(order)
    # Already filled — cancel is no-op
    await ex.cancel_order(receipt.order_id)
    status = await ex.fetch_order(receipt.order_id)
    assert status.status == "filled"
```

- [ ] **Step 2: Implementation**

`backend/app/exchanges/paper.py`:
```python
"""In-memory paper exchange — deterministic fills for unit tests + dry-run.

Uses the same `execution.slippage_bps.{venue}` and `execution.fee_bps.{venue}.{product}`
registry keys as the Phase 4 backtest, so paper trading semantically matches backtest.
"""

from __future__ import annotations

import time
import uuid

from app.backtest.orders import Order
from app.backtest.state import Product
from app.exchanges.types import (
    Balance,
    ExchangePosition,
    OrderReceipt,
    OrderStatus,
)
from app.profile.params import ProfileParams

_BPS_DIVISOR = 10_000.0


class PaperExchange:
    """Deterministic in-memory exchange. ``set_mark_price`` controls fill price."""

    def __init__(
        self,
        *,
        venue: str,
        params: ProfileParams,
        initial_cash: float,
    ) -> None:
        self.name = venue
        self._venue = venue
        self._params = params
        self._cash: float = initial_cash
        self._positions: dict[tuple[str, Product], ExchangePosition] = {}
        self._marks: dict[tuple[str, Product], float] = {}
        self._orders: dict[str, OrderStatus] = {}

    def set_mark_price(self, symbol: str, product: Product, px: float) -> None:
        """Test helper: set the mark price used for fills + mark-to-market."""
        self._marks[(symbol, product)] = px

    async def fetch_balance(self, quote_currency: str) -> Balance:
        return Balance(
            venue=self._venue,
            quote_currency=quote_currency,
            free=self._cash,
            locked=0.0,
        )

    async def fetch_positions(self) -> tuple[ExchangePosition, ...]:
        return tuple(self._positions.values())

    async def fetch_mark_price(self, symbol: str, product: Product) -> float:
        mark = self._marks.get((symbol, product))
        if mark is None:
            raise KeyError(f"no mark set for {symbol}/{product}")
        return mark

    async def place_order(self, order: Order) -> OrderReceipt:
        order_id = uuid.uuid4().hex
        submitted_ts_ms = int(time.time() * 1000)
        status = self._simulate_fill(order, order_id)
        self._orders[order_id] = status
        return OrderReceipt(
            order_id=order_id,
            venue=self._venue,
            symbol=order.symbol,
            submitted_ts_ms=submitted_ts_ms,
        )

    async def fetch_order(self, order_id: str) -> OrderStatus:
        if order_id not in self._orders:
            raise KeyError(f"unknown order {order_id}")
        return self._orders[order_id]

    async def cancel_order(self, order_id: str) -> None:
        # Market orders fill immediately; cancel is a no-op
        return

    def _simulate_fill(self, order: Order, order_id: str) -> OrderStatus:
        mark = self._marks.get((order.symbol, order.product))
        if mark is None:
            return OrderStatus(
                order_id=order_id, status="rejected", fill_px=None,
                filled_qty_base=0.0, fee_quote=0.0,
                raw={"reason": f"no mark for {order.symbol}/{order.product}"},
            )
        slip_bps = float(self._params.get(f"execution.slippage_bps.{self._venue}"))
        fee_bps = float(
            self._params.get(f"execution.fee_bps.{self._venue}.{order.product}")
        )
        slip = slip_bps / _BPS_DIVISOR
        if order.order_type == "market":
            fill_px = mark * (1.0 + slip) if order.side == "buy" else mark * (1.0 - slip)
        else:
            # Limit orders: assume fill iff mark touched the limit
            if order.limit_px is None:
                return OrderStatus(
                    order_id=order_id, status="rejected", fill_px=None,
                    filled_qty_base=0.0, fee_quote=0.0,
                    raw={"reason": "limit order without limit_px"},
                )
            if order.side == "buy" and mark <= order.limit_px:
                fill_px = order.limit_px
            elif order.side == "sell" and mark >= order.limit_px:
                fill_px = order.limit_px
            else:
                return OrderStatus(
                    order_id=order_id, status="pending", fill_px=None,
                    filled_qty_base=0.0, fee_quote=0.0, raw={},
                )
        notional = abs(order.qty_base) * fill_px
        fee = notional * (fee_bps / _BPS_DIVISOR)
        if order.side == "buy":
            cost = notional + fee
            if cost > self._cash:
                return OrderStatus(
                    order_id=order_id, status="rejected", fill_px=None,
                    filled_qty_base=0.0, fee_quote=0.0,
                    raw={"reason": f"insufficient cash {self._cash} < {cost}"},
                )
            self._cash -= cost
        else:
            self._cash += notional - fee

        self._apply_position(order, fill_px)
        return OrderStatus(
            order_id=order_id, status="filled", fill_px=fill_px,
            filled_qty_base=order.qty_base, fee_quote=fee, raw={},
        )

    def _apply_position(self, order: Order, fill_px: float) -> None:
        key = (order.symbol, order.product)
        delta = order.qty_base if order.side == "buy" else -order.qty_base
        existing = self._positions.get(key)
        if existing is None:
            self._positions[key] = ExchangePosition(
                venue=self._venue, symbol=order.symbol, product=order.product,
                qty_base=delta, avg_entry_px=fill_px,
                mark_px=fill_px, unrealized_pnl_quote=0.0,
            )
            return
        new_qty = existing.qty_base + delta
        if new_qty == 0.0:
            del self._positions[key]
            return
        same_sign = (delta * existing.qty_base) > 0
        if same_sign:
            new_avg = (
                (existing.avg_entry_px * abs(existing.qty_base))
                + (fill_px * abs(delta))
            ) / (abs(existing.qty_base) + abs(delta))
        else:
            new_avg = existing.avg_entry_px
        self._positions[key] = ExchangePosition(
            venue=self._venue, symbol=order.symbol, product=order.product,
            qty_base=new_qty, avg_entry_px=new_avg,
            mark_px=fill_px, unrealized_pnl_quote=0.0,
        )
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/exchanges/test_paper.py -v
git add backend/app/exchanges/paper.py backend/tests/exchanges/test_paper.py
git commit -m "feat: PaperExchange in-memory adapter for unit tests + dry-run"
```

---

### Task 7: BinanceExchange REST adapter (skeleton + HMAC auth)

**Files:**
- Create: `backend/app/exchanges/binance.py`
- Create: `backend/tests/exchanges/test_binance.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for BinanceExchange REST adapter."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.backtest.orders import Order
from app.exchanges.binance import BinanceExchange
from app.exchanges.errors import AuthFailed, Rejected
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.asyncio
async def test_fetch_balance_parses_response() -> None:
    def handler(req: Request) -> Response:
        assert "X-MBX-APIKEY" in req.headers
        assert "signature=" in req.url.query.decode()
        return Response(
            200,
            json={
                "balances": [
                    {"asset": "USDC", "free": "9876.5", "locked": "100.0"},
                    {"asset": "BTC", "free": "0.1", "locked": "0.0"},
                ]
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher,
            params=_params(),
            api_key="test-key",
            api_secret="test-secret",
            base_url="https://testnet.binance.vision",
        )
        b = await ex.fetch_balance("USDC")
    assert b.free == 9876.5
    assert b.locked == 100.0
    assert b.quote_currency == "USDC"


@pytest.mark.asyncio
async def test_place_market_order_sends_signed_body() -> None:
    captured = {}

    def handler(req: Request) -> Response:
        captured["url"] = str(req.url)
        captured["headers"] = dict(req.headers)
        return Response(
            200,
            json={
                "orderId": 12345,
                "symbol": "BTCUSDT",
                "transactTime": 1714521600000,
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher, params=_params(),
            api_key="test-key", api_secret="test-secret",
            base_url="https://testnet.binance.vision",
        )
        order = Order(
            venue="binance", symbol="BTCUSDT", product="spot",
            side="buy", qty_base=0.1, order_type="market",
        )
        receipt = await ex.place_order(order)

    assert receipt.order_id == "12345"
    assert "signature=" in captured["url"]
    assert captured["headers"]["X-MBX-APIKEY"] == "test-key"


@pytest.mark.asyncio
async def test_auth_failure_raises() -> None:
    def handler(req: Request) -> Response:
        return Response(401, json={"code": -2014, "msg": "API-key format invalid."})

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, max_retries=0, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher, params=_params(),
            api_key="bad", api_secret="bad",
            base_url="https://testnet.binance.vision",
        )
        with pytest.raises(AuthFailed):
            await ex.fetch_balance("USDC")


@pytest.mark.asyncio
async def test_400_raises_rejected() -> None:
    def handler(req: Request) -> Response:
        return Response(400, json={"code": -1013, "msg": "Filter failure: LOT_SIZE"})

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, max_retries=0, base_backoff_s=0.0)
        ex = BinanceExchange(
            fetcher=fetcher, params=_params(),
            api_key="test", api_secret="test",
            base_url="https://testnet.binance.vision",
        )
        order = Order(
            venue="binance", symbol="BTCUSDT", product="spot",
            side="buy", qty_base=0.000001, order_type="market",
        )
        with pytest.raises(Rejected):
            await ex.place_order(order)
```

- [ ] **Step 2: Implementation**

`backend/app/exchanges/binance.py`:
```python
"""Binance REST adapter (spot + USDS-margined perp).

Auth: HMAC SHA256 over the query string, header ``X-MBX-APIKEY``.
Phase 5 ships with mocked HTTP only; real testnet integration is Phase 7.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse
from typing import Any

import httpx

from app.backtest.orders import Order
from app.backtest.state import Product
from app.exchanges.errors import AuthFailed, Rejected
from app.exchanges.types import (
    Balance,
    ExchangePosition,
    OrderReceipt,
    OrderStatus,
)
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams

_RECV_WINDOW_MS = 5000
_AUTH_FAIL_CODES: set[int] = {401, 403}
_REJECTED_CODES: set[int] = {400, 422}


class BinanceExchange:
    name = "binance"

    def __init__(
        self,
        *,
        fetcher: RetryingFetcher,
        params: ProfileParams,
        api_key: str,
        api_secret: str,
        base_url: str,
    ) -> None:
        self._fetcher = fetcher
        self._params = params
        self._api_key = api_key
        self._api_secret = api_secret
        self._base = base_url.rstrip("/")

    def _sign(self, params: dict[str, Any]) -> str:
        query = urllib.parse.urlencode(params)
        sig = hmac.new(
            self._api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={sig}"

    def _headers(self) -> dict[str, str]:
        return {"X-MBX-APIKEY": self._api_key}

    async def _signed_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "timestamp": int(time.time() * 1000), "recvWindow": _RECV_WINDOW_MS}
        url = f"{self._base}{path}?{self._sign(params)}"
        try:
            result = await self._fetcher.get_json(url, headers=self._headers())
        except RuntimeError as e:
            self._maybe_raise(e)
            raise
        return result  # type: ignore[return-value]

    async def _signed_post(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "timestamp": int(time.time() * 1000), "recvWindow": _RECV_WINDOW_MS}
        url = f"{self._base}{path}?{self._sign(params)}"
        # Binance signed POST uses query string for signature; empty body
        try:
            async with httpx.AsyncClient() as raw:
                resp = await raw.post(url, headers=self._headers(), timeout=10.0)
        except httpx.RequestError as e:
            raise RuntimeError(f"post {path}: {e}") from e
        if resp.status_code in _AUTH_FAIL_CODES:
            raise AuthFailed(f"binance auth failure on {path}: {resp.text}")
        if resp.status_code in _REJECTED_CODES:
            raise Rejected(f"binance rejected {path}: {resp.text}")
        if resp.status_code != 200:
            raise RuntimeError(f"binance {path}: {resp.status_code} {resp.text}")
        return resp.json()

    @staticmethod
    def _maybe_raise(err: RuntimeError) -> None:
        msg = str(err)
        for code in _AUTH_FAIL_CODES:
            if f"HTTP {code}" in msg:
                raise AuthFailed(msg) from err
        for code in _REJECTED_CODES:
            if f"HTTP {code}" in msg:
                raise Rejected(msg) from err

    async def fetch_balance(self, quote_currency: str) -> Balance:
        body = await self._signed_get("/api/v3/account", {})
        for entry in body.get("balances", []):
            if entry["asset"] == quote_currency:
                return Balance(
                    venue=self.name,
                    quote_currency=quote_currency,
                    free=float(entry["free"]),
                    locked=float(entry["locked"]),
                )
        return Balance(venue=self.name, quote_currency=quote_currency, free=0.0, locked=0.0)

    async def fetch_positions(self) -> tuple[ExchangePosition, ...]:
        # Phase 5: stub. Real implementation needs both spot holdings + perp positionRisk.
        # Returning empty tuple is correct for a fresh testnet account.
        return ()

    async def place_order(self, order: Order) -> OrderReceipt:
        params: dict[str, Any] = {
            "symbol": order.symbol,
            "side": order.side.upper(),
            "type": "MARKET" if order.order_type == "market" else "LIMIT",
            "quantity": str(order.qty_base),
        }
        if order.order_type == "limit":
            assert order.limit_px is not None
            params["price"] = str(order.limit_px)
            params["timeInForce"] = "GTC"
        path = "/api/v3/order"
        body = await self._signed_post(path, params)
        return OrderReceipt(
            order_id=str(body["orderId"]),
            venue=self.name,
            symbol=order.symbol,
            submitted_ts_ms=int(body.get("transactTime", time.time() * 1000)),
        )

    async def fetch_order(self, order_id: str) -> OrderStatus:
        # Phase 5: stub. Use orderId query; symbol required by Binance API.
        # In OMS, we always pass the symbol via the place_order receipt mapping;
        # a real implementation would carry the symbol through.
        return OrderStatus(
            order_id=order_id, status="pending", fill_px=None,
            filled_qty_base=0.0, fee_quote=0.0, raw={},
        )

    async def cancel_order(self, order_id: str) -> None:
        return

    async def fetch_mark_price(self, symbol: str, product: Product) -> float:
        body = await self._signed_get(
            "/api/v3/ticker/price", {"symbol": symbol}
        )
        return float(body["price"])
```

Note: `fetch_positions` + `fetch_order` are stubs for Phase 5 — full implementation needs symbol pass-through and additional endpoints (perp positionRisk). Real testnet validation in Phase 7 will exercise these properly. Keeping them as stubs here keeps the PR focused.

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/exchanges/test_binance.py -v
git add backend/app/exchanges/binance.py backend/tests/exchanges/test_binance.py
git commit -m "feat: BinanceExchange REST adapter with HMAC signing"
```

---

### Task 8: BybitExchange REST adapter

**Files:**
- Create: `backend/app/exchanges/bybit.py`
- Create: `backend/tests/exchanges/test_bybit.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for BybitExchange REST adapter."""

from __future__ import annotations

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.backtest.orders import Order
from app.exchanges.bybit import BybitExchange
from app.exchanges.errors import AuthFailed
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.asyncio
async def test_fetch_balance_parses_v5_response() -> None:
    def handler(req: Request) -> Response:
        assert req.headers.get("X-BAPI-API-KEY") == "test-key"
        assert "X-BAPI-SIGN" in req.headers
        return Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "list": [
                        {
                            "coin": [
                                {"coin": "USDT", "free": "5000.0", "locked": "0.0"}
                            ]
                        }
                    ]
                },
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BybitExchange(
            fetcher=fetcher, params=_params(),
            api_key="test-key", api_secret="test-secret",
            base_url="https://api-testnet.bybit.com",
        )
        b = await ex.fetch_balance("USDT")
    assert b.free == 5000.0


@pytest.mark.asyncio
async def test_place_market_order_returns_order_id() -> None:
    def handler(req: Request) -> Response:
        return Response(
            200,
            json={
                "retCode": 0,
                "result": {"orderId": "abc-123", "orderLinkId": "x"},
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = BybitExchange(
            fetcher=fetcher, params=_params(),
            api_key="t", api_secret="t",
            base_url="https://api-testnet.bybit.com",
        )
        order = Order(
            venue="bybit", symbol="BTCUSDT", product="perp",
            side="sell", qty_base=0.05, order_type="market",
        )
        receipt = await ex.place_order(order)
    assert receipt.order_id == "abc-123"


@pytest.mark.asyncio
async def test_auth_failure_raises() -> None:
    def handler(req: Request) -> Response:
        return Response(200, json={"retCode": 10003, "retMsg": "Invalid API key"})

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, max_retries=0, base_backoff_s=0.0)
        ex = BybitExchange(
            fetcher=fetcher, params=_params(),
            api_key="bad", api_secret="bad",
            base_url="https://api-testnet.bybit.com",
        )
        with pytest.raises(AuthFailed):
            await ex.fetch_balance("USDT")
```

- [ ] **Step 2: Implementation**

`backend/app/exchanges/bybit.py`:
```python
"""Bybit V5 REST adapter (unified margin: spot + perp).

Auth: HMAC SHA256 over ``timestamp + api_key + recv_window + (queryString | body)``,
header ``X-BAPI-SIGN``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from app.backtest.orders import Order
from app.backtest.state import Product
from app.exchanges.errors import AuthFailed, Rejected
from app.exchanges.types import (
    Balance,
    ExchangePosition,
    OrderReceipt,
    OrderStatus,
)
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams

_RECV_WINDOW_MS = "5000"
_AUTH_FAIL_RET_CODES: set[int] = {10003, 10004, 10005, 33004}


class BybitExchange:
    name = "bybit"

    def __init__(
        self,
        *,
        fetcher: RetryingFetcher,
        params: ProfileParams,
        api_key: str,
        api_secret: str,
        base_url: str,
    ) -> None:
        self._fetcher = fetcher
        self._params = params
        self._api_key = api_key
        self._api_secret = api_secret
        self._base = base_url.rstrip("/")

    def _sign(self, ts_ms: str, payload: str) -> str:
        msg = f"{ts_ms}{self._api_key}{_RECV_WINDOW_MS}{payload}"
        return hmac.new(
            self._api_secret.encode(),
            msg.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self, ts_ms: str, payload: str) -> dict[str, str]:
        return {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-TIMESTAMP": ts_ms,
            "X-BAPI-RECV-WINDOW": _RECV_WINDOW_MS,
            "X-BAPI-SIGN": self._sign(ts_ms, payload),
        }

    def _check_response(self, body: dict[str, Any]) -> None:
        code = int(body.get("retCode", -1))
        if code == 0:
            return
        if code in _AUTH_FAIL_RET_CODES:
            raise AuthFailed(f"bybit retCode {code}: {body.get('retMsg')}")
        raise Rejected(f"bybit retCode {code}: {body.get('retMsg')}")

    async def fetch_balance(self, quote_currency: str) -> Balance:
        ts_ms = str(int(time.time() * 1000))
        query = "accountType=UNIFIED"
        url = f"{self._base}/v5/account/wallet-balance?{query}"
        headers = self._headers(ts_ms, query)
        body = await self._fetcher.get_json(url, headers=headers)
        self._check_response(body)  # type: ignore[arg-type]
        wallet_list = body["result"]["list"]  # type: ignore[index]
        if not wallet_list:
            return Balance(venue=self.name, quote_currency=quote_currency, free=0.0, locked=0.0)
        for coin in wallet_list[0]["coin"]:
            if coin["coin"] == quote_currency:
                return Balance(
                    venue=self.name,
                    quote_currency=quote_currency,
                    free=float(coin["free"]),
                    locked=float(coin["locked"]),
                )
        return Balance(venue=self.name, quote_currency=quote_currency, free=0.0, locked=0.0)

    async def fetch_positions(self) -> tuple[ExchangePosition, ...]:
        return ()

    async def place_order(self, order: Order) -> OrderReceipt:
        ts_ms = str(int(time.time() * 1000))
        body_obj: dict[str, Any] = {
            "category": "linear" if order.product == "perp" else "spot",
            "symbol": order.symbol,
            "side": order.side.capitalize(),
            "orderType": "Market" if order.order_type == "market" else "Limit",
            "qty": str(order.qty_base),
        }
        if order.order_type == "limit":
            assert order.limit_px is not None
            body_obj["price"] = str(order.limit_px)
            body_obj["timeInForce"] = "GTC"
        payload = json.dumps(body_obj, separators=(",", ":"))
        url = f"{self._base}/v5/order/create"
        headers = self._headers(ts_ms, payload)
        try:
            async with httpx.AsyncClient() as raw:
                resp = await raw.post(url, content=payload, headers=headers, timeout=10.0)
        except httpx.RequestError as e:
            raise RuntimeError(f"bybit place_order: {e}") from e
        if resp.status_code == 401:
            raise AuthFailed(resp.text)
        if resp.status_code >= 400:
            raise Rejected(f"bybit place_order: {resp.status_code} {resp.text}")
        data = resp.json()
        self._check_response(data)
        return OrderReceipt(
            order_id=str(data["result"]["orderId"]),
            venue=self.name,
            symbol=order.symbol,
            submitted_ts_ms=int(ts_ms),
        )

    async def fetch_order(self, order_id: str) -> OrderStatus:
        return OrderStatus(
            order_id=order_id, status="pending", fill_px=None,
            filled_qty_base=0.0, fee_quote=0.0, raw={},
        )

    async def cancel_order(self, order_id: str) -> None:
        return

    async def fetch_mark_price(self, symbol: str, product: Product) -> float:
        category = "linear" if product == "perp" else "spot"
        url = f"{self._base}/v5/market/tickers?category={category}&symbol={symbol}"
        body = await self._fetcher.get_json(url)
        self._check_response(body)  # type: ignore[arg-type]
        return float(body["result"]["list"][0]["lastPrice"])  # type: ignore[index]
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/exchanges/test_bybit.py -v
git add backend/app/exchanges/bybit.py backend/tests/exchanges/test_bybit.py
git commit -m "feat: BybitExchange V5 REST adapter with HMAC signing"
```

---

### Task 9: HyperliquidExchange REST adapter (EIP-712)

**Files:**
- Create: `backend/app/exchanges/hyperliquid.py`
- Create: `backend/tests/exchanges/test_hyperliquid.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for HyperliquidExchange REST adapter."""

from __future__ import annotations

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.backtest.orders import Order
from app.exchanges.hyperliquid import HyperliquidExchange
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams

# Test EVM key (dev only) — generates a deterministic wallet
_TEST_KEY = "0x" + "1" * 64


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.asyncio
async def test_fetch_balance_parses_clearinghouse_state() -> None:
    def handler(req: Request) -> Response:
        body = req.content
        assert b'"type":"clearinghouseState"' in body or b'"type": "clearinghouseState"' in body
        return Response(
            200,
            json={
                "marginSummary": {"accountValue": "1234.56", "totalRawUsd": "1200.0"},
                "withdrawable": "1100.0",
                "assetPositions": [],
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = HyperliquidExchange(
            fetcher=fetcher, params=_params(),
            wallet_private_key=_TEST_KEY,
            base_url="https://api.hyperliquid-testnet.xyz",
        )
        b = await ex.fetch_balance("USDC")
    assert b.free == 1100.0
    assert b.quote_currency == "USDC"


@pytest.mark.asyncio
async def test_place_order_sends_signed_payload() -> None:
    def handler(req: Request) -> Response:
        return Response(
            200,
            json={
                "status": "ok",
                "response": {
                    "type": "order",
                    "data": {
                        "statuses": [{"resting": {"oid": 99}}],
                    },
                },
            },
        )

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        ex = HyperliquidExchange(
            fetcher=fetcher, params=_params(),
            wallet_private_key=_TEST_KEY,
            base_url="https://api.hyperliquid-testnet.xyz",
        )
        order = Order(
            venue="hyperliquid", symbol="BTC", product="perp",
            side="buy", qty_base=0.01, order_type="market",
        )
        receipt = await ex.place_order(order)
    assert receipt.order_id == "99"
```

- [ ] **Step 2: Implementation**

`backend/app/exchanges/hyperliquid.py`:
```python
"""Hyperliquid REST adapter.

Hyperliquid is an L1 with a centralised order book API. Auth is via EVM-style
signing: each action is signed with the user's EVM private key. Phase 5 ships
mocked HTTP only; real signature verification by HL is exercised in Phase 7.

Phase 5 simplification: place_order ships a structured payload with an
``eth_account``-generated signature. We do NOT exercise HL's exact EIP-712
type hash here — that's calibrated in Phase 7 against real testnet responses.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

from app.backtest.orders import Order
from app.backtest.state import Product
from app.exchanges.errors import AuthFailed, Rejected
from app.exchanges.types import (
    Balance,
    ExchangePosition,
    OrderReceipt,
    OrderStatus,
)
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams


class HyperliquidExchange:
    name = "hyperliquid"

    def __init__(
        self,
        *,
        fetcher: RetryingFetcher,
        params: ProfileParams,
        wallet_private_key: str,
        base_url: str,
    ) -> None:
        self._fetcher = fetcher
        self._params = params
        self._account = Account.from_key(wallet_private_key)
        self._base = base_url.rstrip("/")

    def _address(self) -> str:
        return self._account.address

    def _sign_message(self, message: str) -> str:
        signed = self._account.sign_message(encode_defunct(text=message))
        return signed.signature.hex()

    async def _info(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}/info"
        return await self._fetcher.post_json(url, body=body)  # type: ignore[return-value]

    async def fetch_balance(self, quote_currency: str) -> Balance:
        # quote_currency unused — HL clearinghouse is USDC-denominated only
        body = await self._info(
            {"type": "clearinghouseState", "user": self._address()}
        )
        withdrawable = float(body.get("withdrawable", "0"))
        return Balance(
            venue=self.name,
            quote_currency="USDC",
            free=withdrawable,
            locked=0.0,
        )

    async def fetch_positions(self) -> tuple[ExchangePosition, ...]:
        body = await self._info(
            {"type": "clearinghouseState", "user": self._address()}
        )
        positions: list[ExchangePosition] = []
        for asset_pos in body.get("assetPositions", []):
            pos = asset_pos.get("position", {})
            sz = float(pos.get("szi", "0"))
            if sz == 0:
                continue
            positions.append(
                ExchangePosition(
                    venue=self.name,
                    symbol=pos["coin"],
                    product="perp",
                    qty_base=sz,
                    avg_entry_px=float(pos.get("entryPx", "0")),
                    mark_px=float(pos.get("entryPx", "0")),
                    unrealized_pnl_quote=float(pos.get("unrealizedPnl", "0")),
                )
            )
        return tuple(positions)

    async def place_order(self, order: Order) -> OrderReceipt:
        # Phase 5 simplified payload — real HL action signing is calibrated in Phase 7
        action = {
            "type": "order",
            "orders": [
                {
                    "coin": order.symbol,
                    "is_buy": order.side == "buy",
                    "sz": order.qty_base,
                    "limit_px": order.limit_px if order.limit_px else 0.0,
                    "order_type": {"limit": {"tif": "Gtc"}}
                    if order.order_type == "limit"
                    else {"trigger": {"isMarket": True}},
                    "reduce_only": False,
                }
            ],
            "grouping": "na",
        }
        nonce_ms = int(time.time() * 1000)
        signature = self._sign_message(f"{self._address()}{nonce_ms}")
        payload = {
            "action": action,
            "nonce": nonce_ms,
            "signature": signature,
        }
        url = f"{self._base}/exchange"
        try:
            async with httpx.AsyncClient() as raw:
                resp = await raw.post(url, json=payload, timeout=10.0)
        except httpx.RequestError as e:
            raise RuntimeError(f"hyperliquid place_order: {e}") from e
        if resp.status_code == 401 or resp.status_code == 403:
            raise AuthFailed(resp.text)
        if resp.status_code >= 400:
            raise Rejected(f"hyperliquid place_order: {resp.status_code} {resp.text}")
        body = resp.json()
        if body.get("status") != "ok":
            raise Rejected(f"hyperliquid: {body}")
        data = body["response"]["data"]["statuses"][0]
        oid = data.get("resting", data.get("filled", {})).get("oid")
        return OrderReceipt(
            order_id=str(oid),
            venue=self.name,
            symbol=order.symbol,
            submitted_ts_ms=nonce_ms,
        )

    async def fetch_order(self, order_id: str) -> OrderStatus:
        return OrderStatus(
            order_id=order_id, status="pending", fill_px=None,
            filled_qty_base=0.0, fee_quote=0.0, raw={},
        )

    async def cancel_order(self, order_id: str) -> None:
        return

    async def fetch_mark_price(self, symbol: str, product: Product) -> float:
        body = await self._info({"type": "allMids"})
        if symbol in body:
            return float(body[symbol])  # type: ignore[index]
        raise KeyError(f"no mark for {symbol} on hyperliquid")
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/exchanges/test_hyperliquid.py -v
git add backend/app/exchanges/hyperliquid.py backend/tests/exchanges/test_hyperliquid.py
git commit -m "feat: HyperliquidExchange REST adapter with EVM signing"
```

---

## Phase 5.4: Decision audit + ORM

### Task 10: DecisionAuditEntry ORM

**Files:**
- Create: `backend/app/models/decision_audit.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Implementation**

`backend/app/models/decision_audit.py`:
```python
"""DecisionAuditEntry ORM — per-decision audit row (Constraint #4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DecisionAuditEntry(Base):
    __tablename__ = "decision_audit_entries"
    __table_args__ = (
        Index("ix_decision_audit_strategy_ts", "strategy_name", "ts"),
        Index("ix_decision_audit_profile_hash_ts", "profile_hash", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(80), nullable=False)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_profiles.id"), nullable=False
    )
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(20), nullable=False)
    input_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    orders: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    fills: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    reconciliation_status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

Update `backend/app/models/__init__.py`:
```python
"""ORM models. Import models here so Alembic autogenerate picks them up."""

from app.models.backtest_run import BacktestRun
from app.models.base import Base
from app.models.data_health_event import DataHealthEvent
from app.models.decision_audit import DecisionAuditEntry
from app.models.strategy_profile import StrategyProfile
from app.models.symbol_manifest_snapshot import SymbolManifestSnapshot

__all__ = [
    "Base",
    "BacktestRun",
    "DataHealthEvent",
    "DecisionAuditEntry",
    "StrategyProfile",
    "SymbolManifestSnapshot",
]
```

- [ ] **Step 2: Gates green**

```bash
just typecheck && just lint && just test
```
Expected: prior tests still pass; mypy +1 source file; ruff clean.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/decision_audit.py backend/app/models/__init__.py
git commit -m "feat: DecisionAuditEntry ORM"
```

---

### Task 11: Alembic migration 0004

**Files:**
- Create: `backend/alembic/versions/0004_create_decision_audit_entries.py`

- [ ] **Step 1: Autogenerate**

```bash
cd backend && uv run alembic revision --autogenerate -m "create_decision_audit_entries"
```

- [ ] **Step 2: Rename to `0004_create_decision_audit_entries.py` and normalize header**

```python
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None
```

Verify `upgrade()` creates `decision_audit_entries` table with all columns from the ORM + the two indexes. Strip any orphan `ix_strategy_profiles_active` diff (carried bug from Phase 3).

Order imports per ruff I001 (sqlalchemy before alembic).

- [ ] **Step 3: Apply + verify**

```bash
just mig-up
docker compose exec postgres psql -U cryptobot -d cryptobot -c "\d decision_audit_entries" | head -25
```

- [ ] **Step 4: Round-trip**

```bash
cd backend && uv run alembic downgrade 0003 && uv run alembic upgrade head
```

- [ ] **Step 5: Gates + commit**

```bash
just typecheck && just lint && just test
git add backend/alembic/versions/0004_create_decision_audit_entries.py
git commit -m "feat: alembic migration adding decision_audit_entries table"
```

---

### Task 12: DecisionAuditService

**Files:**
- Create: `backend/app/services/decision_audit.py`
- Create: `backend/tests/services/test_decision_audit.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for DecisionAuditService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile
from app.services.decision_audit import DecisionAuditService


async def _make_profile(db_session: AsyncSession) -> StrategyProfile:
    p = StrategyProfile(name="audit-svc", version=1, is_active=False, config={})
    db_session.add(p)
    await db_session.flush()
    return p


@pytest.mark.asyncio
async def test_log_decision_creates_row(db_session: AsyncSession) -> None:
    p = await _make_profile(db_session)
    svc = DecisionAuditService(db_session)
    entry = await svc.log_decision(
        ts=datetime(2026, 5, 24, tzinfo=UTC),
        strategy_name="funding_arb",
        profile_id=p.id,
        profile_version=p.version,
        profile_hash="abc",
        input_state={"cash": 1000.0},
        orders=[{"symbol": "BTCUSDT"}],
        fills=[{"fill_px": 60000.0}],
        reconciliation_status="ok",
    )
    assert entry.id is not None
    assert entry.decision_type == "order"


@pytest.mark.asyncio
async def test_log_snapshot_creates_row_with_empty_orders(db_session: AsyncSession) -> None:
    p = await _make_profile(db_session)
    svc = DecisionAuditService(db_session)
    entry = await svc.log_snapshot(
        ts=datetime(2026, 5, 24, tzinfo=UTC),
        strategy_name="funding_arb",
        profile_id=p.id,
        profile_version=p.version,
        profile_hash="abc",
        input_state={"cash": 1000.0},
    )
    assert entry.decision_type == "snapshot"
    assert entry.orders == []
    assert entry.fills == []


@pytest.mark.asyncio
async def test_get_recent_returns_filtered_entries(db_session: AsyncSession) -> None:
    p = await _make_profile(db_session)
    svc = DecisionAuditService(db_session)
    for i in range(3):
        await svc.log_decision(
            ts=datetime(2026, 5, 24, tzinfo=UTC),
            strategy_name="funding_arb",
            profile_id=p.id,
            profile_version=p.version,
            profile_hash="abc",
            input_state={},
            orders=[],
            fills=[],
            reconciliation_status="ok",
        )
    entries = await svc.get_recent(limit=10, strategy_name="funding_arb")
    assert len(entries) == 3
```

- [ ] **Step 2: Implementation**

`backend/app/services/decision_audit.py`:
```python
"""DecisionAuditService — write + query DecisionAuditEntry rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_audit import DecisionAuditEntry


class DecisionAuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log_decision(
        self,
        *,
        ts: datetime,
        strategy_name: str,
        profile_id: uuid.UUID,
        profile_version: int,
        profile_hash: str,
        input_state: dict[str, Any],
        orders: list[Any],
        fills: list[Any],
        reconciliation_status: str,
        reason: str | None = None,
    ) -> DecisionAuditEntry:
        entry = DecisionAuditEntry(
            ts=ts,
            strategy_name=strategy_name,
            profile_id=profile_id,
            profile_version=profile_version,
            profile_hash=profile_hash,
            decision_type="order",
            input_state=input_state,
            orders=orders,
            fills=fills,
            reconciliation_status=reconciliation_status,
            reason=reason,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def log_snapshot(
        self,
        *,
        ts: datetime,
        strategy_name: str,
        profile_id: uuid.UUID,
        profile_version: int,
        profile_hash: str,
        input_state: dict[str, Any],
    ) -> DecisionAuditEntry:
        entry = DecisionAuditEntry(
            ts=ts,
            strategy_name=strategy_name,
            profile_id=profile_id,
            profile_version=profile_version,
            profile_hash=profile_hash,
            decision_type="snapshot",
            input_state=input_state,
            orders=[],
            fills=[],
            reconciliation_status="ok",
            reason=None,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def get_recent(
        self,
        *,
        limit: int = 50,
        strategy_name: str | None = None,
        decision_type: str | None = None,
    ) -> list[DecisionAuditEntry]:
        stmt = (
            select(DecisionAuditEntry)
            .order_by(DecisionAuditEntry.ts.desc())
            .limit(limit)
        )
        if strategy_name is not None:
            stmt = stmt.where(DecisionAuditEntry.strategy_name == strategy_name)
        if decision_type is not None:
            stmt = stmt.where(DecisionAuditEntry.decision_type == decision_type)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/services/test_decision_audit.py -v
git add backend/app/services/decision_audit.py backend/tests/services/test_decision_audit.py
git commit -m "feat: DecisionAuditService log_decision + log_snapshot + get_recent"
```

---

## Phase 5.5: OMS internals

### Task 13: OMS package skeleton + KillSwitch

**Files:**
- Create: `backend/app/oms/__init__.py`
- Create: `backend/app/oms/exceptions.py`
- Create: `backend/app/oms/kill_switch.py`
- Create: `backend/tests/oms/__init__.py`
- Create: `backend/tests/oms/test_kill_switch.py`

- [ ] **Step 1: Failing test**

`backend/tests/oms/test_kill_switch.py`:
```python
"""Tests for KillSwitch."""

from __future__ import annotations

from app.oms.kill_switch import KillSwitch
from app.profile.params import ProfileParams


def test_default_is_inactive() -> None:
    ks = KillSwitch(params=ProfileParams(profile={}))
    assert ks.is_active() is False


def test_profile_flag_activates_kill_switch() -> None:
    ks = KillSwitch(params=ProfileParams(profile={"oms": {"kill_switch_active": True}}))
    assert ks.is_active() is True
```

- [ ] **Step 2: Implementation**

`backend/app/oms/__init__.py`:
```python
"""Order Management System — dispatches strategy orders to live exchanges."""
```

`backend/app/oms/exceptions.py`:
```python
"""OMS exception hierarchy — halt-class errors that suspend trading."""

from __future__ import annotations


class OMSError(RuntimeError):
    """Base class for all OMS errors."""


class KillSwitchActive(OMSError):
    """Kill switch flag is set in the active profile; refuse to dispatch."""


class HedgeDriftHalt(OMSError):
    """Spot/perp position mismatch exceeded threshold."""


class ReconciliationDriftHalt(OMSError):
    """Book vs exchange position mismatch exceeded threshold."""


class UnconfiguredVenueError(OMSError):
    """Strategy emitted an order for a venue with no configured adapter."""
```

`backend/app/oms/kill_switch.py`:
```python
"""KillSwitch — reads `oms.kill_switch_active` from the profile registry."""

from __future__ import annotations

from app.profile.params import ProfileParams


class KillSwitch:
    def __init__(self, *, params: ProfileParams) -> None:
        self._params = params

    def is_active(self) -> bool:
        return bool(self._params.get("oms.kill_switch_active"))
```

`backend/tests/oms/__init__.py`: empty.

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/oms/test_kill_switch.py -v
git add backend/app/oms backend/tests/oms
git commit -m "feat: OMS package skeleton + KillSwitch + exceptions"
```

---

### Task 14: PositionReconciler

**Files:**
- Create: `backend/app/oms/reconciler.py`
- Create: `backend/tests/oms/test_reconciler.py`

- [ ] **Step 1: Failing test**

`backend/tests/oms/test_reconciler.py`:
```python
"""Tests for PositionReconciler — book vs exchange + hedge consistency drift."""

from __future__ import annotations

import pytest

from app.backtest.state import Position
from app.exchanges.types import ExchangePosition
from app.oms.exceptions import HedgeDriftHalt, ReconciliationDriftHalt
from app.oms.reconciler import PositionReconciler
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def _book_pos(qty: float, product: str = "spot", symbol: str = "BTCUSDT") -> Position:
    return Position(
        venue="binance", symbol=symbol, product=product,  # type: ignore[arg-type]
        qty_base=qty, avg_entry_px=60000.0,
    )


def _exchange_pos(qty: float, product: str = "spot", symbol: str = "BTCUSDT") -> ExchangePosition:
    return ExchangePosition(
        venue="binance", symbol=symbol, product=product,  # type: ignore[arg-type]
        qty_base=qty, avg_entry_px=60000.0,
        mark_px=60000.0, unrealized_pnl_quote=0.0,
    )


def test_no_drift_ok() -> None:
    r = PositionReconciler(params=_params())
    r.check_book_vs_exchange(
        book_positions=(_book_pos(0.1),),
        exchange_positions=(_exchange_pos(0.1),),
    )  # no raise


def test_book_drift_under_threshold_ok() -> None:
    r = PositionReconciler(params=_params())
    # 1% drift on a 0.1 position: 0.001 difference; threshold is 2%
    r.check_book_vs_exchange(
        book_positions=(_book_pos(0.1),),
        exchange_positions=(_exchange_pos(0.101),),
    )


def test_book_drift_over_threshold_raises() -> None:
    r = PositionReconciler(params=_params())
    # 5% drift on a 0.1 position: 0.005 difference; threshold is 2%
    with pytest.raises(ReconciliationDriftHalt):
        r.check_book_vs_exchange(
            book_positions=(_book_pos(0.1),),
            exchange_positions=(_exchange_pos(0.105),),
        )


def test_cold_start_empty_book_is_ok() -> None:
    r = PositionReconciler(params=_params())
    # Empty book + exchange has a position → cold start, no halt
    r.check_book_vs_exchange(
        book_positions=(),
        exchange_positions=(_exchange_pos(0.1),),
    )


def test_hedge_consistency_no_drift() -> None:
    r = PositionReconciler(params=_params())
    r.check_hedge_consistency(
        positions=(_book_pos(0.1, "spot"), _book_pos(-0.1, "perp")),
    )


def test_hedge_consistency_drift_over_threshold_raises() -> None:
    r = PositionReconciler(params=_params())
    # 10% drift: spot 0.1, perp -0.11; threshold 5%
    with pytest.raises(HedgeDriftHalt):
        r.check_hedge_consistency(
            positions=(_book_pos(0.1, "spot"), _book_pos(-0.11, "perp")),
        )


def test_hedge_consistency_no_perp_pair_is_ok() -> None:
    r = PositionReconciler(params=_params())
    # Only spot → not a hedge pair, no check
    r.check_hedge_consistency(
        positions=(_book_pos(0.1, "spot"),),
    )
```

- [ ] **Step 2: Implementation**

`backend/app/oms/reconciler.py`:
```python
"""PositionReconciler — halt-class drift detection.

Two checks per dispatch:
  1. Book vs exchange — our PositionBook's qty must match what the exchange reports.
     Drift > ``oms.reconcile_drift_halt_pct`` raises ``ReconciliationDriftHalt``.
  2. Hedge consistency — for symbols with both spot + perp positions, the qty
     magnitudes must match (delta-neutral). Drift > ``oms.hedge_drift_halt_pct``
     raises ``HedgeDriftHalt``.
"""

from __future__ import annotations

from app.backtest.state import Position
from app.exchanges.types import ExchangePosition
from app.oms.exceptions import HedgeDriftHalt, ReconciliationDriftHalt
from app.profile.params import ProfileParams

_EPSILON = 1e-9


class PositionReconciler:
    def __init__(self, *, params: ProfileParams) -> None:
        self._params = params

    def check_book_vs_exchange(
        self,
        *,
        book_positions: tuple[Position, ...],
        exchange_positions: tuple[ExchangePosition, ...],
    ) -> None:
        threshold = float(self._params.get("oms.reconcile_drift_halt_pct"))
        book_map: dict[tuple[str, str, str], float] = {
            (p.venue, p.symbol, p.product): p.qty_base for p in book_positions
        }
        ex_map: dict[tuple[str, str, str], float] = {
            (p.venue, p.symbol, p.product): p.qty_base for p in exchange_positions
        }
        for key, book_qty in book_map.items():
            if abs(book_qty) < _EPSILON:
                continue
            ex_qty = ex_map.get(key, 0.0)
            diff = abs(book_qty - ex_qty)
            pct = diff / max(abs(book_qty), _EPSILON)
            if pct > threshold:
                raise ReconciliationDriftHalt(
                    f"book vs exchange drift {pct:.4f} on {key}: "
                    f"book={book_qty}, exchange={ex_qty}, threshold={threshold}"
                )

    def check_hedge_consistency(
        self,
        *,
        positions: tuple[Position, ...],
    ) -> None:
        threshold = float(self._params.get("oms.hedge_drift_halt_pct"))
        by_symbol: dict[tuple[str, str], dict[str, float]] = {}
        for p in positions:
            key = (p.venue, p.symbol)
            by_symbol.setdefault(key, {})[p.product] = p.qty_base
        for (venue, symbol), products in by_symbol.items():
            if "spot" not in products or "perp" not in products:
                continue
            spot_qty = abs(products["spot"])
            perp_qty = abs(products["perp"])
            if spot_qty < _EPSILON:
                continue
            drift_pct = abs(spot_qty - perp_qty) / spot_qty
            if drift_pct > threshold:
                raise HedgeDriftHalt(
                    f"hedge drift {drift_pct:.4f} on {venue}/{symbol}: "
                    f"|spot|={spot_qty}, |perp|={perp_qty}, threshold={threshold}"
                )
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/oms/test_reconciler.py -v
git add backend/app/oms/reconciler.py backend/tests/oms/test_reconciler.py
git commit -m "feat: PositionReconciler with book + hedge drift detection"
```

---

### Task 15: MultiVenueCashLedger

**Files:**
- Create: `backend/app/oms/ledger.py`
- Create: `backend/tests/oms/test_ledger.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for MultiVenueCashLedger."""

from __future__ import annotations

from app.oms.ledger import MultiVenueCashLedger


def test_initial_balance_zero() -> None:
    ledger = MultiVenueCashLedger()
    assert ledger.total() == 0.0


def test_set_venue_balance() -> None:
    ledger = MultiVenueCashLedger()
    ledger.set_venue_balance("binance", 5000.0)
    ledger.set_venue_balance("hyperliquid", 3000.0)
    assert ledger.total() == 8000.0
    assert ledger.get_venue_balance("binance") == 5000.0


def test_debit_credit() -> None:
    ledger = MultiVenueCashLedger()
    ledger.set_venue_balance("binance", 5000.0)
    ledger.debit("binance", 1000.0)
    assert ledger.get_venue_balance("binance") == 4000.0
    ledger.credit("binance", 500.0)
    assert ledger.get_venue_balance("binance") == 4500.0


def test_get_unknown_venue_returns_zero() -> None:
    ledger = MultiVenueCashLedger()
    assert ledger.get_venue_balance("unknown") == 0.0
```

- [ ] **Step 2: Implementation**

`backend/app/oms/ledger.py`:
```python
"""MultiVenueCashLedger — tracks USDC across venues as a single logical pool."""

from __future__ import annotations


class MultiVenueCashLedger:
    def __init__(self) -> None:
        self._balances: dict[str, float] = {}

    def set_venue_balance(self, venue: str, amount: float) -> None:
        self._balances[venue] = amount

    def get_venue_balance(self, venue: str) -> float:
        return self._balances.get(venue, 0.0)

    def debit(self, venue: str, amount: float) -> None:
        self._balances[venue] = self.get_venue_balance(venue) - amount

    def credit(self, venue: str, amount: float) -> None:
        self._balances[venue] = self.get_venue_balance(venue) + amount

    def total(self) -> float:
        return sum(self._balances.values())

    def to_dict(self) -> dict[str, float]:
        return dict(self._balances)
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/oms/test_ledger.py -v
git add backend/app/oms/ledger.py backend/tests/oms/test_ledger.py
git commit -m "feat: MultiVenueCashLedger USDC across venues"
```

---

### Task 16: OMS service — dispatch happy path

**Files:**
- Create: `backend/app/oms/service.py`
- Create: `backend/tests/oms/test_dispatch.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for OMS.dispatch — happy path with paper adapters."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.orders import Order
from app.backtest.state import MarketSnapshot, MarketState
from app.exchanges.paper import PaperExchange
from app.models.strategy_profile import StrategyProfile
from app.oms.kill_switch import KillSwitch
from app.oms.ledger import MultiVenueCashLedger
from app.oms.reconciler import PositionReconciler
from app.oms.service import OMS
from app.profile.params import ProfileParams
from app.services.decision_audit import DecisionAuditService


def _state() -> MarketState:
    return MarketState(
        snapshot=MarketSnapshot(ts_ms=1714521600000, bars={}),
        positions=(),
        cash_quote=10_000.0,
    )


@pytest.mark.asyncio
async def test_dispatch_single_order_returns_fills(db_session: AsyncSession) -> None:
    params = ProfileParams(profile={})
    paper = PaperExchange(venue="binance", params=params, initial_cash=10_000.0)
    paper.set_mark_price("BTCUSDT", "spot", 60000.0)

    profile = StrategyProfile(name="oms-test", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()

    oms = OMS(
        exchanges={"binance": paper},
        audit_service=DecisionAuditService(db_session),
        params=params,
        kill_switch=KillSwitch(params=params),
        reconciler=PositionReconciler(params=params),
        ledger=MultiVenueCashLedger(),
    )

    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot",
        side="buy", qty_base=0.1, order_type="market",
    )
    result = await oms.dispatch(
        orders=[order],
        state=_state(),
        strategy_name="test_strategy",
        profile_id=profile.id,
        profile_version=1,
        profile_hash="abc",
    )

    assert len(result.fills) == 1
    assert result.fills[0].fill_px == pytest.approx(60030.0)
    assert result.reconciliation_status == "ok"
    assert result.audit_entry_id is not None


@pytest.mark.asyncio
async def test_dispatch_kill_switch_active_raises(db_session: AsyncSession) -> None:
    from app.oms.exceptions import KillSwitchActive

    params = ProfileParams(profile={"oms": {"kill_switch_active": True}})
    paper = PaperExchange(venue="binance", params=params, initial_cash=10_000.0)
    paper.set_mark_price("BTCUSDT", "spot", 60000.0)

    profile = StrategyProfile(name="oms-kill", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()

    oms = OMS(
        exchanges={"binance": paper},
        audit_service=DecisionAuditService(db_session),
        params=params,
        kill_switch=KillSwitch(params=params),
        reconciler=PositionReconciler(params=params),
        ledger=MultiVenueCashLedger(),
    )

    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot",
        side="buy", qty_base=0.1, order_type="market",
    )
    with pytest.raises(KillSwitchActive):
        await oms.dispatch(
            orders=[order],
            state=_state(),
            strategy_name="test_strategy",
            profile_id=profile.id,
            profile_version=1,
            profile_hash="abc",
        )


@pytest.mark.asyncio
async def test_dispatch_unconfigured_venue_raises(db_session: AsyncSession) -> None:
    from app.oms.exceptions import UnconfiguredVenueError

    params = ProfileParams(profile={})
    profile = StrategyProfile(name="oms-uc", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()

    oms = OMS(
        exchanges={},  # no adapters
        audit_service=DecisionAuditService(db_session),
        params=params,
        kill_switch=KillSwitch(params=params),
        reconciler=PositionReconciler(params=params),
        ledger=MultiVenueCashLedger(),
    )

    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot",
        side="buy", qty_base=0.1, order_type="market",
    )
    with pytest.raises(UnconfiguredVenueError):
        await oms.dispatch(
            orders=[order],
            state=_state(),
            strategy_name="test_strategy",
            profile_id=profile.id,
            profile_version=1,
            profile_hash="abc",
        )
```

- [ ] **Step 2: Implementation**

`backend/app/oms/service.py`:
```python
"""OMS service — dispatch strategy orders to live exchanges with reconciliation."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.backtest.orders import Fill, Order
from app.backtest.state import MarketState
from app.exchanges.base import Exchange
from app.exchanges.errors import AuthFailed, ExchangeError
from app.oms.exceptions import (
    HedgeDriftHalt,
    KillSwitchActive,
    OMSError,
    ReconciliationDriftHalt,
    UnconfiguredVenueError,
)
from app.oms.kill_switch import KillSwitch
from app.oms.ledger import MultiVenueCashLedger
from app.oms.reconciler import PositionReconciler
from app.profile.params import ProfileParams
from app.services.decision_audit import DecisionAuditService


@dataclass
class DispatchResult:
    fills: list[Fill]
    audit_entry_id: uuid.UUID
    reconciliation_status: str
    reason: str | None = None


class OMS:
    def __init__(
        self,
        *,
        exchanges: dict[str, Exchange],
        audit_service: DecisionAuditService,
        params: ProfileParams,
        kill_switch: KillSwitch,
        reconciler: PositionReconciler,
        ledger: MultiVenueCashLedger,
    ) -> None:
        self._exchanges = exchanges
        self._audit = audit_service
        self._params = params
        self._kill_switch = kill_switch
        self._reconciler = reconciler
        self._ledger = ledger

    async def dispatch(
        self,
        *,
        orders: list[Order],
        state: MarketState,
        strategy_name: str,
        profile_id: uuid.UUID,
        profile_version: int,
        profile_hash: str,
    ) -> DispatchResult:
        ts = datetime.now(UTC)
        input_state = _serialize_state(state)
        order_dicts = [_serialize_order(o) for o in orders]

        # 1. Kill switch check (before any exchange contact)
        if self._kill_switch.is_active():
            entry = await self._audit.log_decision(
                ts=ts,
                strategy_name=strategy_name,
                profile_id=profile_id,
                profile_version=profile_version,
                profile_hash=profile_hash,
                input_state=input_state,
                orders=order_dicts,
                fills=[],
                reconciliation_status="kill_switch",
                reason="kill switch active",
            )
            raise KillSwitchActive(
                f"kill switch active; audit_entry_id={entry.id}"
            )

        # 2. Validate each order's venue is configured
        for order in orders:
            if order.venue not in self._exchanges:
                entry = await self._audit.log_decision(
                    ts=ts,
                    strategy_name=strategy_name,
                    profile_id=profile_id,
                    profile_version=profile_version,
                    profile_hash=profile_hash,
                    input_state=input_state,
                    orders=order_dicts,
                    fills=[],
                    reconciliation_status="unconfigured_venue",
                    reason=f"venue {order.venue} not configured",
                )
                raise UnconfiguredVenueError(
                    f"{order.venue} not in configured exchanges; entry={entry.id}"
                )

        # 3. Place orders, poll for fills
        fills: list[Fill] = []
        try:
            for order in orders:
                ex = self._exchanges[order.venue]
                receipt = await ex.place_order(order)
                status = await self._poll_until_terminal(ex, receipt.order_id)
                if status.status in ("filled", "partially_filled"):
                    assert status.fill_px is not None
                    fills.append(
                        Fill(
                            ts_ms=int(time.time() * 1000),
                            order=order,
                            fill_px=status.fill_px,
                            fee_quote=status.fee_quote,
                        )
                    )
        except AuthFailed as e:
            entry = await self._audit.log_decision(
                ts=ts, strategy_name=strategy_name,
                profile_id=profile_id, profile_version=profile_version,
                profile_hash=profile_hash, input_state=input_state,
                orders=order_dicts, fills=[_serialize_fill(f) for f in fills],
                reconciliation_status="auth_failed",
                reason=str(e),
            )
            raise OMSError(f"auth failed; audit_entry_id={entry.id}") from e

        # 4. Reconcile (book vs exchange + hedge consistency)
        reconciliation_status = "ok"
        reason: str | None = None
        try:
            ex_positions: list = []
            for venue in {o.venue for o in orders}:
                ex_positions.extend(await self._exchanges[venue].fetch_positions())
            self._reconciler.check_book_vs_exchange(
                book_positions=state.positions,
                exchange_positions=tuple(ex_positions),
            )
            self._reconciler.check_hedge_consistency(positions=state.positions)
        except HedgeDriftHalt as e:
            reconciliation_status = "halted_hedge_drift"
            reason = str(e)
        except ReconciliationDriftHalt as e:
            reconciliation_status = "halted_book_drift"
            reason = str(e)

        # 5. Audit log + return
        entry = await self._audit.log_decision(
            ts=ts,
            strategy_name=strategy_name,
            profile_id=profile_id,
            profile_version=profile_version,
            profile_hash=profile_hash,
            input_state=input_state,
            orders=order_dicts,
            fills=[_serialize_fill(f) for f in fills],
            reconciliation_status=reconciliation_status,
            reason=reason,
        )

        if reconciliation_status == "halted_hedge_drift":
            assert reason is not None
            raise HedgeDriftHalt(reason)
        if reconciliation_status == "halted_book_drift":
            assert reason is not None
            raise ReconciliationDriftHalt(reason)

        return DispatchResult(
            fills=fills,
            audit_entry_id=entry.id,
            reconciliation_status=reconciliation_status,
            reason=reason,
        )

    async def _poll_until_terminal(self, ex: Exchange, order_id: str):  # type: ignore[no-untyped-def]
        import asyncio

        poll_interval = float(self._params.get("oms.fill_poll_interval_s"))
        max_wait = float(self._params.get("oms.max_fill_wait_s"))
        deadline = time.monotonic() + max_wait
        while True:
            status = await ex.fetch_order(order_id)
            if status.status in ("filled", "partially_filled", "cancelled", "rejected"):
                return status
            if time.monotonic() >= deadline:
                # Time-out; cancel + return whatever the final status is
                await ex.cancel_order(order_id)
                return status
            await asyncio.sleep(poll_interval)


def _serialize_order(o: Order) -> dict:
    return {
        "venue": o.venue,
        "symbol": o.symbol,
        "product": o.product,
        "side": o.side,
        "qty_base": o.qty_base,
        "order_type": o.order_type,
        "limit_px": o.limit_px,
    }


def _serialize_fill(f: Fill) -> dict:
    return {
        "ts_ms": f.ts_ms,
        "fill_px": f.fill_px,
        "fee_quote": f.fee_quote,
        "order": _serialize_order(f.order),
    }


def _serialize_state(state: MarketState) -> dict:
    return {
        "ts_ms": state.snapshot.ts_ms,
        "cash_quote": state.cash_quote,
        "positions": [
            {
                "venue": p.venue, "symbol": p.symbol, "product": p.product,
                "qty_base": p.qty_base, "avg_entry_px": p.avg_entry_px,
            }
            for p in state.positions
        ],
    }
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/oms/test_dispatch.py -v
git add backend/app/oms/service.py backend/tests/oms/test_dispatch.py
git commit -m "feat: OMS.dispatch happy path + kill switch + unconfigured venue"
```

---

### Task 17: OMS reconciliation drift tests

**Files:**
- Modify: `backend/tests/oms/test_dispatch.py` (append tests)

- [ ] **Step 1: Failing tests (append)**

```python
@pytest.mark.asyncio
async def test_dispatch_hedge_drift_raises(db_session: AsyncSession) -> None:
    from app.backtest.state import Position
    from app.oms.exceptions import HedgeDriftHalt

    params = ProfileParams(profile={})
    paper = PaperExchange(venue="binance", params=params, initial_cash=10_000.0)
    paper.set_mark_price("BTCUSDT", "spot", 60000.0)

    profile = StrategyProfile(name="oms-hedge", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()

    # Synthetic state: spot 0.1, perp -0.11 → 10% drift, > 5% threshold
    drifted_state = MarketState(
        snapshot=MarketSnapshot(ts_ms=1714521600000, bars={}),
        positions=(
            Position(venue="binance", symbol="BTCUSDT", product="spot",
                     qty_base=0.1, avg_entry_px=60000.0),
            Position(venue="binance", symbol="BTCUSDT", product="perp",
                     qty_base=-0.11, avg_entry_px=60000.0),
        ),
        cash_quote=10_000.0,
    )

    oms = OMS(
        exchanges={"binance": paper},
        audit_service=DecisionAuditService(db_session),
        params=params,
        kill_switch=KillSwitch(params=params),
        reconciler=PositionReconciler(params=params),
        ledger=MultiVenueCashLedger(),
    )

    # Empty orders list — no exchange interaction; just trigger reconciliation
    with pytest.raises(HedgeDriftHalt):
        await oms.dispatch(
            orders=[],
            state=drifted_state,
            strategy_name="test_strategy",
            profile_id=profile.id,
            profile_version=1,
            profile_hash="abc",
        )
```

- [ ] **Step 2: Verify FAILS or passes already (depending on Task 16 implementation)**

The Task 16 OMS already calls the reconciler. This test should pass directly. If it fails, it means the empty-orders path doesn't reach the reconciler — fix by ensuring the reconciliation block runs unconditionally after the order-placement loop.

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/oms/test_dispatch.py -v
git add backend/tests/oms/test_dispatch.py
git commit -m "test: OMS dispatch hedge drift halt"
```

---

## Phase 5.6: API + audit-trail integration

### Task 18: POST /api/v1/oms/kill endpoint

**Files:**
- Create: `backend/app/api/oms.py`
- Create: `backend/app/schemas/oms.py`
- Modify: `backend/app/main.py` (register router)
- Create: `backend/tests/api/test_oms.py`

- [ ] **Step 1: Failing test**

`backend/tests/api/test_oms.py`:
```python
"""Tests for /api/v1/oms endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile


@pytest.mark.asyncio
async def test_status_returns_kill_switch_false_by_default(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    p = StrategyProfile(name="oms-status-default", version=1, is_active=True, config={})
    db_session.add(p)
    await db_session.flush()
    await db_session.commit()
    r = await async_client.get("/api/v1/oms/status")
    assert r.status_code == 200
    assert r.json()["kill_switch_active"] is False


@pytest.mark.asyncio
async def test_post_kill_flips_flag(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    p = StrategyProfile(name="oms-kill", version=1, is_active=True, config={})
    db_session.add(p)
    await db_session.flush()
    await db_session.commit()
    r = await async_client.post("/api/v1/oms/kill", json={"reason": "test"})
    assert r.status_code == 200
    body = r.json()
    assert body["kill_switch_active"] is True
    # Status endpoint reflects the new state
    s = await async_client.get("/api/v1/oms/status")
    assert s.json()["kill_switch_active"] is True
```

- [ ] **Step 2: Implementation**

`backend/app/schemas/oms.py`:
```python
"""Pydantic v2 schemas for OMS endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class KillRequest(BaseModel):
    reason: str | None = None


class KillResponse(BaseModel):
    active_profile_id: str
    kill_switch_active: bool
    new_version: int


class VenueStatus(BaseModel):
    name: str
    configured: bool
    use_testnet: bool


class OMSStatusResponse(BaseModel):
    kill_switch_active: bool
    active_profile_id: str | None
    active_profile_version: int | None
    last_dispatch_ts: datetime | None
    last_reconciliation_status: str | None
    venues: list[VenueStatus]
```

`backend/app/api/oms.py`:
```python
"""HTTP API for OMS state + kill switch toggle."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.models.decision_audit import DecisionAuditEntry
from app.models.strategy_profile import StrategyProfile
from app.profile.params import ProfileParams
from app.schemas.oms import KillRequest, KillResponse, OMSStatusResponse, VenueStatus

router = APIRouter(prefix="/api/v1/oms", tags=["oms"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _active_profile(db: AsyncSession) -> StrategyProfile | None:
    result = await db.execute(
        select(StrategyProfile).where(StrategyProfile.is_active.is_(True))
    )
    return result.scalar_one_or_none()


@router.post("/kill", response_model=KillResponse)
async def kill(body: KillRequest, db: DbSession) -> KillResponse:
    profile = await _active_profile(db)
    if profile is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "no active profile to flip"
        )
    # Mutate config: set oms.kill_switch_active = True
    new_config = dict(profile.config) if profile.config else {}
    oms_section = dict(new_config.get("oms", {}))
    oms_section["kill_switch_active"] = True
    new_config["oms"] = oms_section
    profile.config = new_config
    profile.version = profile.version + 1
    await db.flush()
    await db.commit()
    return KillResponse(
        active_profile_id=str(profile.id),
        kill_switch_active=True,
        new_version=profile.version,
    )


@router.get("/status", response_model=OMSStatusResponse)
async def status_endpoint(db: DbSession) -> OMSStatusResponse:
    profile = await _active_profile(db)
    if profile is None:
        return OMSStatusResponse(
            kill_switch_active=False,
            active_profile_id=None,
            active_profile_version=None,
            last_dispatch_ts=None,
            last_reconciliation_status=None,
            venues=[
                VenueStatus(name=v, configured=False, use_testnet=True)
                for v in ("binance", "bybit", "hyperliquid")
            ],
        )
    params = ProfileParams(profile=profile.config)
    last = await db.execute(
        select(DecisionAuditEntry)
        .order_by(DecisionAuditEntry.ts.desc())
        .limit(1)
    )
    last_entry = last.scalar_one_or_none()
    return OMSStatusResponse(
        kill_switch_active=bool(params.get("oms.kill_switch_active")),
        active_profile_id=str(profile.id),
        active_profile_version=profile.version,
        last_dispatch_ts=last_entry.ts if last_entry else None,
        last_reconciliation_status=last_entry.reconciliation_status if last_entry else None,
        venues=[
            VenueStatus(
                name=v,
                configured=False,  # Phase 7+ will reflect env-key presence
                use_testnet=bool(params.get(f"exchanges.{v}.use_testnet")),
            )
            for v in ("binance", "bybit", "hyperliquid")
        ],
    )
```

Modify `backend/app/main.py` — add `oms` to the `from app.api import ...` list and call `app.include_router(oms.router)`.

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/api/test_oms.py -v
git add backend/app/api/oms.py backend/app/schemas/oms.py backend/app/main.py backend/tests/api/test_oms.py
git commit -m "feat: POST /api/v1/oms/kill + GET /api/v1/oms/status"
```

---

### Task 19: GET /api/v1/decision-audit/recent endpoint

**Files:**
- Create: `backend/app/api/decision_audit.py`
- Create: `backend/app/schemas/decision_audit.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_decision_audit.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for /api/v1/decision-audit endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_audit import DecisionAuditEntry
from app.models.strategy_profile import StrategyProfile


@pytest.mark.asyncio
async def test_recent_returns_entries(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    p = StrategyProfile(name="da-test", version=1, is_active=False, config={})
    db_session.add(p)
    await db_session.flush()

    entry = DecisionAuditEntry(
        ts=datetime(2026, 5, 24, tzinfo=UTC),
        strategy_name="funding_arb",
        profile_id=p.id,
        profile_version=1,
        profile_hash="abc",
        decision_type="order",
        input_state={},
        orders=[],
        fills=[],
        reconciliation_status="ok",
    )
    db_session.add(entry)
    await db_session.flush()
    await db_session.commit()

    r = await async_client.get("/api/v1/decision-audit/recent")
    assert r.status_code == 200
    assert any(e["strategy_name"] == "funding_arb" for e in r.json())


@pytest.mark.asyncio
async def test_recent_filters_by_strategy(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    p = StrategyProfile(name="da-filter", version=1, is_active=False, config={})
    db_session.add(p)
    await db_session.flush()

    for name in ("strat_a", "strat_b"):
        db_session.add(DecisionAuditEntry(
            ts=datetime(2026, 5, 24, tzinfo=UTC),
            strategy_name=name,
            profile_id=p.id, profile_version=1, profile_hash="x",
            decision_type="order", input_state={}, orders=[], fills=[],
            reconciliation_status="ok",
        ))
    await db_session.flush()
    await db_session.commit()

    r = await async_client.get("/api/v1/decision-audit/recent?strategy_name=strat_a")
    assert r.status_code == 200
    names = {e["strategy_name"] for e in r.json()}
    assert "strat_a" in names
    assert "strat_b" not in names
```

- [ ] **Step 2: Implementation**

`backend/app/schemas/decision_audit.py`:
```python
"""Pydantic v2 schemas for decision-audit endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DecisionAuditResponse(BaseModel):
    id: uuid.UUID
    ts: datetime
    strategy_name: str
    profile_id: uuid.UUID
    profile_version: int
    profile_hash: str
    decision_type: str
    input_state: dict[str, Any]
    orders: list[Any]
    fills: list[Any]
    reconciliation_status: str
    reason: str | None
    created_at: datetime
```

`backend/app/api/decision_audit.py`:
```python
"""HTTP API for recent decision-audit entries."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.schemas.decision_audit import DecisionAuditResponse
from app.services.decision_audit import DecisionAuditService

router = APIRouter(prefix="/api/v1/decision-audit", tags=["decision-audit"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

_DEFAULT_LIMIT = 50


@router.get("/recent", response_model=list[DecisionAuditResponse])
async def recent(
    db: DbSession,
    limit: int = _DEFAULT_LIMIT,
    strategy_name: str | None = None,
    decision_type: str | None = None,
) -> list[DecisionAuditResponse]:
    svc = DecisionAuditService(db)
    entries = await svc.get_recent(
        limit=limit,
        strategy_name=strategy_name,
        decision_type=decision_type,
    )
    return [
        DecisionAuditResponse.model_validate(e, from_attributes=True) for e in entries
    ]
```

Modify `backend/app/main.py` to register the router.

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/api/test_decision_audit.py -v
git add backend/app/api/decision_audit.py backend/app/schemas/decision_audit.py backend/app/main.py backend/tests/api/test_decision_audit.py
git commit -m "feat: GET /api/v1/decision-audit/recent endpoint"
```

---

### Task 20: Audit-trail test (Constraint #4)

**Files:**
- Create: `backend/tests/oms/test_audit_trail.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for OMS audit trail — profile_hash locks at dispatch time."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.orders import Order
from app.backtest.state import MarketSnapshot, MarketState
from app.exchanges.paper import PaperExchange
from app.models.decision_audit import DecisionAuditEntry
from app.models.strategy_profile import StrategyProfile
from app.oms.kill_switch import KillSwitch
from app.oms.ledger import MultiVenueCashLedger
from app.oms.reconciler import PositionReconciler
from app.oms.service import OMS
from app.profile.params import ProfileParams
from app.services.decision_audit import DecisionAuditService


def _hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.asyncio
async def test_dispatch_writes_audit_with_provided_hash(
    db_session: AsyncSession,
) -> None:
    params = ProfileParams(profile={})
    paper = PaperExchange(venue="binance", params=params, initial_cash=10_000.0)
    paper.set_mark_price("BTCUSDT", "spot", 60000.0)

    profile = StrategyProfile(name="audit-trail", version=3, is_active=False, config={"x": 1})
    db_session.add(profile)
    await db_session.flush()

    locked_hash = _hash({"x": 1})

    oms = OMS(
        exchanges={"binance": paper},
        audit_service=DecisionAuditService(db_session),
        params=params,
        kill_switch=KillSwitch(params=params),
        reconciler=PositionReconciler(params=params),
        ledger=MultiVenueCashLedger(),
    )
    order = Order(
        venue="binance", symbol="BTCUSDT", product="spot",
        side="buy", qty_base=0.1, order_type="market",
    )
    result = await oms.dispatch(
        orders=[order],
        state=MarketState(
            snapshot=MarketSnapshot(ts_ms=1714521600000, bars={}),
            positions=(), cash_quote=10_000.0,
        ),
        strategy_name="test_strategy",
        profile_id=profile.id,
        profile_version=profile.version,
        profile_hash=locked_hash,
    )

    # Mutate the profile after dispatch
    profile.config = {"x": 9999}
    profile.version = profile.version + 1
    await db_session.flush()

    # The audit entry must still reflect the OLD hash + version
    row = (
        await db_session.execute(
            select(DecisionAuditEntry).where(DecisionAuditEntry.id == result.audit_entry_id)
        )
    ).scalar_one()
    assert row.profile_hash == locked_hash
    assert row.profile_version == 3
```

- [ ] **Step 2: Tests pass + commit**

```bash
cd backend && uv run pytest tests/oms/test_audit_trail.py -v
git add backend/tests/oms/test_audit_trail.py
git commit -m "test: OMS audit trail locks profile_hash at dispatch"
```

---

## Phase 5.7: Lint + README + PR

### Task 21: Extend AST literal lint to OMS + exchanges

**Files:**
- Modify: `scripts/lint_no_literals_in_strategies.py`

- [ ] **Step 1: Add scan targets**

In `SCAN_TARGETS`, append:
```python
    REPO_ROOT / "backend" / "app" / "oms",
    REPO_ROOT / "backend" / "app" / "exchanges",
```

- [ ] **Step 2: Run lint**

```bash
python3 scripts/lint_no_literals_in_strategies.py
```

Likely violations from these modules:
- `paper.py`: `_BPS_DIVISOR = 10_000.0` (module constant — already exempt)
- `binance.py`: `_RECV_WINDOW_MS = 5000`, `_AUTH_FAIL_CODES`, `_REJECTED_CODES` (sets) — module constants, exempt
- `bybit.py`: similar pattern, module constants
- `hyperliquid.py`: no module-level literals beyond `_EPSILON`-style — should be clean
- `service.py`: `int(time.time() * 1000)` — `1000` is a unit-of-measure constant; either extract as `_MS_PER_SECOND = 1000` or use `time.time_ns() // 1_000_000`. Pick the constant.
- `reconciler.py`: `_EPSILON = 1e-9` (module constant — exempt)

Fix any violations by extracting to module-level `_NAME = literal` constants (or pulling to registry if it's tunable). The lint's existing carveouts (set literals at module scope, Pow exponents, subscript indices) apply.

- [ ] **Step 3: Existing `test_ast_lint.py` still passes**

```bash
cd backend && uv run pytest tests/test_ast_lint.py -v
```

- [ ] **Step 4: Commit**

```bash
git add scripts/lint_no_literals_in_strategies.py backend/app/oms backend/app/exchanges
git commit -m "chore: extend AST literal lint to oms + exchanges"
```

---

### Task 22: README + final sweep

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append section** after the "Backtester (Phase 4)" block:

````markdown

## OMS + Exchange adapters (Phase 5)

The OMS bridges `Strategy.evaluate()` output to live exchanges with the same
profile-driven contract the backtest uses. Every dispatch is audit-logged with
the active profile's `profile_hash` (Constraint #4).

### Configured venues

- `binance` — Binance spot + USDS-margined perp (HMAC signing)
- `bybit` — Bybit V5 (HMAC signing)
- `hyperliquid` — Hyperliquid perp (EVM-signed)

Phase 5 ships **mocked HTTP only**. Real testnet integration is Phase 7.

### API keys (env-only, never in DB)

```bash
export BINANCE_API_KEY=...
export BINANCE_API_SECRET=...
export BYBIT_API_KEY=...
export BYBIT_API_SECRET=...
export HYPERLIQUID_WALLET_PRIVATE_KEY=...
```

Phase 0 ops checklist covers key creation: withdrawals disabled, IP whitelist.

### Kill switch

```bash
# Flip the active profile's kill switch (halts all OMS dispatches)
curl -X POST http://localhost:8000/api/v1/oms/kill -H "Content-Type: application/json" -d '{"reason":"manual halt"}'

# Check status
curl http://localhost:8000/api/v1/oms/status

# Recent decisions
curl http://localhost:8000/api/v1/decision-audit/recent
```

### Halt classes

- `KillSwitchActive` — `oms.kill_switch_active` flag is set
- `HedgeDriftHalt` — spot/perp position drift > `oms.hedge_drift_halt_pct` (default 5%)
- `ReconciliationDriftHalt` — book vs exchange drift > `oms.reconcile_drift_halt_pct` (default 2%)
- `UnconfiguredVenueError` — strategy emitted an order for a venue not in the OMS exchange map
````

- [ ] **Step 2: Full sweep**

```bash
just typecheck && just lint && just test
```
Expected: ~135 tests pass (Phase 4 final 122 + ~13 from Phase 5).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README OMS + exchange adapters section"
```

---

### Task 23: PR via /pr-summary

- [ ] **Step 1: Confirm gates green**

```bash
just typecheck && just lint && just test
```

- [ ] **Step 2: Invoke /pr-summary**

The parent agent invokes `/pr-summary` to:
- Compute version bump (MINOR — all-additive features; 0.4.0 → 0.5.0)
- Generate CHANGELOG entry
- Bump via `./scripts/bump-version.sh minor`
- Predict next PR number, backfill spec PR ref
- Commit `chore: bump version to v0.5.0`
- Annotated-tag `v0.5.0`
- Push `--follow-tags`
- Open the PR

Do NOT run `gh pr create` directly.

---

## Plan self-review

- **Spec coverage**: registry (Task 1), dataclasses (2-3), config (4), HTTP (5), paper (6), 3 REST adapters (7-9), DB+ORM (10-11), audit service (12), OMS core (13-17), API (18-19), audit trail (20), lint (21), docs (22), PR (23). All spec sections covered.
- **Type consistency**: `Order` reused from Phase 4. `MarketState` reused from Phase 4. `Fill` reused. `Position` reused. New dataclasses `Balance`/`ExchangePosition`/`OrderReceipt`/`OrderStatus` defined Task 2, consumed everywhere consistently. `ProfileParams.get()` extended Task 1 to support `_BOOL_` registry, consumers in Task 13+ (KillSwitch) and Task 14 (PositionReconciler thresholds) and Task 16 (OMS poll intervals).
- **Constraint #1 enforcement**: Task 21 extends AST lint to `app/oms/**` and `app/exchanges/**`. Module-level `_NAME = literal` carveout (from Phase 4) covers all unit-of-measure constants used in adapters (`_BPS_DIVISOR`, `_RECV_WINDOW_MS`, `_AUTH_FAIL_CODES`).
- **Constraint #4 enforcement**: every `OMS.dispatch()` writes exactly one `DecisionAuditEntry`. The audit-trail test (Task 20) verifies `profile_hash` is locked at dispatch and survives subsequent profile mutation.
- **TDD discipline**: every task has RED → GREEN → COMMIT (except pure-additive ORM/types tasks where the test in the dependent task covers them).
- **Frequent commits**: 23 commits, mean ~80 LOC each.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-24-cryptobot-oms.md`. Per user's "keep going autonomously" instruction, executing via subagent-driven-development with no further approval pause.
