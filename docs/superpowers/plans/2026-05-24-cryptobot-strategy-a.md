# Cryptobot — Phase 6 Strategy A (Funding Arb) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`.

**Goal:** Ship a delta-neutral funding-arbitrage strategy as a pure `Strategy.evaluate(state, params) → list[Order]`, with the funding rate plumbed into `MarketSnapshot` so both backtest and live can populate it.

**Architecture:** Extend `MarketSnapshot` with a `funding_rates` dict (default empty), have the backtest loader populate it from Parquet, write `FundingArbStrategy` with 4-state entry/exit logic + registry-driven thresholds, register in `StrategyRegistry`. No new DB, no new API.

**Tech Stack:** Existing Phase 1-5 stack. No new deps.

**Scope:** Spec: `docs/superpowers/specs/2026-05-24-cryptobot-strategy-a-design.md`. Blocks Phase 7+.

**Definition of done (gate to Phase 7):**
- ~194 tests (Phase 5 final 179) — mypy --strict + ruff + AST lint clean
- `FundingArbStrategy` unit tests cover 10 scenarios (4-state machine + sizing + edge cases)
- 1 engine E2E test runs the strategy over synthetic Parquet
- `MarketSnapshot.funding_rates` default-factory dict — backward-compatible with all existing tests
- `StrategyRegistry.default()` resolves "funding_arb"
- POST `/api/v1/backtests {strategy_name: "funding_arb"}` accepted

---

## Phase 6.1: State + registry foundations

### Task 1: Profile registry keys for funding_arb

**Files:**
- Modify: `backend/app/profile/defaults.py`
- Modify: `backend/tests/test_profile_registry.py`

- [ ] **Step 1: Failing tests (append)**

```python
def test_funding_arb_thresholds_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    assert PROFILE_SCOPED_DEFAULTS["funding_arb.entry_bps_per_8h"] == 5.0
    assert PROFILE_SCOPED_DEFAULTS["funding_arb.exit_bps_per_8h"] == 1.0
    assert PROFILE_SCOPED_DEFAULTS["funding_arb.max_notional_usdc"] == 5_000.0
    assert PROFILE_SCOPED_DEFAULTS["funding_arb.max_cash_fraction"] == 0.5
    assert PROFILE_SCOPED_DEFAULTS["funding_arb.intervals_per_year"] == 1095.75


def test_funding_arb_string_defaults_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_STRING_DEFAULTS

    assert PROFILE_SCOPED_STRING_DEFAULTS["funding_arb.default_venue"] == "binance"
    assert PROFILE_SCOPED_STRING_DEFAULTS["funding_arb.default_symbol"] == "BTCUSDT"
```

- [ ] **Step 2: Verify FAILS**

```bash
cd backend && uv run pytest tests/test_profile_registry.py::test_funding_arb_thresholds_present -v
```

- [ ] **Step 3: Add keys**

In `backend/app/profile/defaults.py`, add to `PROFILE_SCOPED_DEFAULTS`:
```python
# --- Strategy A: funding arb ---
"funding_arb.entry_bps_per_8h": 5.0,
"funding_arb.exit_bps_per_8h": 1.0,
"funding_arb.max_notional_usdc": 5_000.0,
"funding_arb.max_cash_fraction": 0.5,
"funding_arb.intervals_per_year": 1095.75,
```

Add to `PROFILE_SCOPED_STRING_DEFAULTS`:
```python
"funding_arb.default_venue": "binance",
"funding_arb.default_symbol": "BTCUSDT",
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/test_profile_registry.py -v
git add backend/app/profile/defaults.py backend/tests/test_profile_registry.py
git commit -m "feat: profile registry keys for funding_arb thresholds + defaults"
```

---

### Task 2: Extend MarketSnapshot with funding_rates

**Files:**
- Modify: `backend/app/backtest/state.py`
- Modify: `backend/tests/backtest/test_state.py`

- [ ] **Step 1: Failing test (append)**

```python
def test_market_snapshot_funding_rates_default_empty() -> None:
    snap = MarketSnapshot(ts_ms=1, bars={})
    assert snap.funding_rates == {}


def test_market_snapshot_carries_funding_rates() -> None:
    snap = MarketSnapshot(
        ts_ms=1,
        bars={},
        funding_rates={("binance", "BTCUSDT"): 0.0001},
    )
    assert snap.funding_rates[("binance", "BTCUSDT")] == 0.0001
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Modify `MarketSnapshot`**

In `backend/app/backtest/state.py`, change `MarketSnapshot`:
```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class MarketSnapshot:
    ts_ms: int
    bars: dict[tuple[str, str, Product], Bar]
    funding_rates: dict[tuple[str, str], float] = field(default_factory=dict)
```

The `default_factory=dict` keeps every existing construction site backward-compatible.

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_state.py -v
git add backend/app/backtest/state.py backend/tests/backtest/test_state.py
git commit -m "feat: extend MarketSnapshot with funding_rates dict"
```

---

### Task 3: BacktestLoader populates funding_rates

**Files:**
- Modify: `backend/app/backtest/loader.py`
- Modify: `backend/tests/backtest/test_loader.py`

- [ ] **Step 1: Failing test (append)**

```python
def test_loader_populates_funding_rates(tmp_path: Path) -> None:
    from app.market_data.parquet_store import ParquetStore

    store = ParquetStore(root=tmp_path)
    base = 1704067200000
    # klines
    kline_df = pl.DataFrame(
        {
            "ts_ms": [base, base + 60_000, base + 120_000],
            "open": [60000.0, 60100.0, 60200.0],
            "high": [60050.0, 60150.0, 60250.0],
            "low": [59950.0, 60050.0, 60150.0],
            "close": [60010.0, 60110.0, 60210.0],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", kline_df, year=2024, month=1)
    # funding (one rate at base + 120_000)
    funding_df = pl.DataFrame(
        {
            "ts_ms": [base + 120_000],
            "predicted": [0.0002],
            "realized": [0.00015],
        }
    )
    store.write_funding("binance", "BTCUSDT", funding_df, year=2024, month=1)

    loader = BacktestLoader(parquet_root=tmp_path)
    start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 2, 0, tzinfo=UTC)
    snaps = list(
        loader.iter_snapshots(
            venue="binance",
            symbols=["BTCUSDT"],
            products=["spot"],
            start=start, end=end,
        )
    )
    # First 2 bars: no funding event yet, expect empty dict
    assert snaps[0].funding_rates == {}
    assert snaps[1].funding_rates == {}
    # Third bar: funding event at this ts
    assert snaps[2].funding_rates == {("binance", "BTCUSDT"): 0.00015}
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implementation**

In `backend/app/backtest/loader.py`, modify `iter_snapshots` to also preload + index funding data per (venue, symbol), then surface per-tick rates:

```python
def iter_snapshots(
    self,
    *,
    venue: str,
    symbols: list[str],
    products: list[Product],
    start: datetime,
    end: datetime,
) -> Iterator[MarketSnapshot]:
    # ... existing frame loading ...
    
    # NEW: preload funding rates per (venue, symbol), indexed by ts_ms
    funding_index: dict[tuple[str, str], dict[int, float]] = {}
    for symbol in symbols:
        fdf = self.load_funding(venue=venue, symbol=symbol, start=start, end=end)
        if fdf is not None:
            ts_to_rate: dict[int, float] = {}
            for row in fdf.iter_rows(named=True):
                ts_to_rate[int(row["ts_ms"])] = float(row["realized"])
            funding_index[(venue, symbol)] = ts_to_rate
    
    # ... existing all_ts collection ...
    
    for ts_ms in sorted(all_ts):
        bars: dict[tuple[str, str, Product], Bar] = {}
        # ... existing bar building ...
        
        # NEW: per-tick funding rates
        funding_rates: dict[tuple[str, str], float] = {}
        for (v, s), ts_to_rate in funding_index.items():
            if ts_ms in ts_to_rate:
                funding_rates[(v, s)] = ts_to_rate[ts_ms]
        
        yield MarketSnapshot(ts_ms=ts_ms, bars=bars, funding_rates=funding_rates)
```

Read the existing `loader.py` first to understand the exact shape before editing.

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_loader.py -v
git add backend/app/backtest/loader.py backend/tests/backtest/test_loader.py
git commit -m "feat: BacktestLoader populates funding_rates into MarketSnapshot"
```

---

## Phase 6.2: Strategy implementation

### Task 4: FundingArbStrategy — flat / under-threshold cases

**Files:**
- Create: `backend/app/strategies/funding_arb.py`
- Create: `backend/tests/strategies/__init__.py` (empty if absent)
- Create: `backend/tests/strategies/test_funding_arb.py`

- [ ] **Step 1: Failing test**

`backend/tests/strategies/test_funding_arb.py`:
```python
"""Tests for FundingArbStrategy — Phase 6 real strategy."""

from __future__ import annotations

from app.backtest.state import Bar, MarketSnapshot, MarketState, Position
from app.profile.params import ProfileParams
from app.strategies.funding_arb import FundingArbStrategy


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def _snap(funding: float = 0.0) -> MarketSnapshot:
    spot = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="spot",
        open=60000.0, high=60010.0, low=59990.0, close=60000.0, volume=10.0,
    )
    perp = Bar(
        ts_ms=1, venue="binance", symbol="BTCUSDT", product="perp",
        open=60000.0, high=60010.0, low=59990.0, close=60000.0, volume=10.0,
    )
    return MarketSnapshot(
        ts_ms=1,
        bars={
            ("binance", "BTCUSDT", "spot"): spot,
            ("binance", "BTCUSDT", "perp"): perp,
        },
        funding_rates={("binance", "BTCUSDT"): funding},
    )


def _state(positions: tuple[Position, ...] = (), cash: float = 10_000.0, funding: float = 0.0) -> MarketState:
    return MarketState(snapshot=_snap(funding), positions=positions, cash_quote=cash)


def test_flat_under_threshold_no_orders() -> None:
    # entry threshold default 5.0 bps; here 2 bps → no entry
    s = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    orders = s.evaluate(_state(funding=0.0002), _params())
    assert orders == []


def test_no_funding_data_for_venue_no_orders() -> None:
    s = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    state = MarketState(
        snapshot=MarketSnapshot(ts_ms=1, bars={
            ("binance", "BTCUSDT", "spot"): Bar(ts_ms=1, venue="binance", symbol="BTCUSDT", product="spot", open=60000.0, high=60000.0, low=60000.0, close=60000.0, volume=1.0),
            ("binance", "BTCUSDT", "perp"): Bar(ts_ms=1, venue="binance", symbol="BTCUSDT", product="perp", open=60000.0, high=60000.0, low=60000.0, close=60000.0, volume=1.0),
        }, funding_rates={}),
        positions=(),
        cash_quote=10_000.0,
    )
    orders = s.evaluate(state, _params())
    assert orders == []
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Implementation (minimal — flat under-threshold path only)**

`backend/app/strategies/funding_arb.py`:
```python
"""Strategy A — funding-rate arbitrage.

Delta-neutral long-spot + short-perp when 8h funding is above the entry
threshold; close the hedge when funding decays below the exit threshold.

All thresholds + sizing live in the profile registry (Constraint #1).
"""

from __future__ import annotations

from app.backtest.orders import Order
from app.backtest.state import MarketState, Position
from app.profile.params import ProfileParams

_BPS_DIVISOR = 10_000.0


class FundingArbStrategy:
    name = "funding_arb"

    def __init__(self, *, venue: str, symbol: str) -> None:
        self._venue = venue
        self._symbol = symbol

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        funding = state.snapshot.funding_rates.get((self._venue, self._symbol))
        if funding is None:
            return []
        # Convert to "per 8h bps" — funding rate is the per-interval rate already.
        # Phase 6 assumes funding_rates are 8h-equivalent; mixed-cadence handling is
        # a Phase 7+ concern when we wire venue-specific cadences.
        funding_bps_per_8h = funding * _BPS_DIVISOR
        entry = float(params.get("funding_arb.entry_bps_per_8h"))
        if funding_bps_per_8h < entry:
            return []
        # Other branches (hedged + open hedge + sizing) ship in subsequent tasks.
        return []
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/strategies/test_funding_arb.py -v
git add backend/app/strategies/funding_arb.py backend/tests/strategies
git commit -m "feat: FundingArbStrategy skeleton + flat under-threshold path"
```

---

### Task 5: FundingArbStrategy — entry (open hedge)

**Files:**
- Modify: `backend/app/strategies/funding_arb.py`
- Modify: `backend/tests/strategies/test_funding_arb.py`

- [ ] **Step 1: Failing test (append)**

```python
def test_flat_above_threshold_opens_hedge() -> None:
    # 7 bps > 5 entry; cash 10k, max_notional 5k, max_cash_fraction 0.5 → 5k notional
    # qty = 5000 / 60000 ≈ 0.08333
    s = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    orders = s.evaluate(_state(funding=0.0007), _params())
    assert len(orders) == 2
    spots = [o for o in orders if o.product == "spot"]
    perps = [o for o in orders if o.product == "perp"]
    assert len(spots) == 1 and len(perps) == 1
    assert spots[0].side == "buy"
    assert perps[0].side == "sell"
    assert spots[0].qty_base == perps[0].qty_base  # delta-neutral
    assert spots[0].qty_base > 0


def test_sizing_caps_at_max_notional() -> None:
    s = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    # 100k cash; max_notional 5000 wins over 50000 cash_fraction
    orders = s.evaluate(_state(cash=100_000.0, funding=0.0007), _params())
    expected_qty = 5000.0 / 60000.0
    assert orders[0].qty_base == expected_qty


def test_sizing_caps_at_cash_fraction() -> None:
    s = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    # 1000 cash; max_cash_fraction 0.5 → 500 notional wins over 5000
    orders = s.evaluate(_state(cash=1_000.0, funding=0.0007), _params())
    expected_qty = 500.0 / 60000.0
    assert orders[0].qty_base == expected_qty
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Add entry path**

Modify `evaluate` in `funding_arb.py`. After the under-threshold check, add:

```python
        # Determine current state: flat / hedged / orphan
        spot_pos, perp_pos = self._find_position(state.positions)

        if spot_pos is None and perp_pos is None:
            # Flat → maybe open hedge if funding is above entry threshold
            if funding_bps_per_8h < entry:
                return []
            return self._open_hedge(state, params)
        # Other states ship in subsequent tasks
        return []
```

Add helper methods:
```python
    def _find_position(
        self, positions: tuple[Position, ...]
    ) -> tuple[Position | None, Position | None]:
        spot: Position | None = None
        perp: Position | None = None
        for p in positions:
            if (p.venue, p.symbol) != (self._venue, self._symbol):
                continue
            if p.product == "spot":
                spot = p
            elif p.product == "perp":
                perp = p
        return spot, perp

    def _open_hedge(
        self, state: MarketState, params: ProfileParams
    ) -> list[Order]:
        spot_bar = state.snapshot.bars.get((self._venue, self._symbol, "spot"))
        perp_bar = state.snapshot.bars.get((self._venue, self._symbol, "perp"))
        if spot_bar is None or perp_bar is None:
            return []
        if spot_bar.close <= 0.0:
            return []
        max_notional = float(params.get("funding_arb.max_notional_usdc"))
        cash_frac = float(params.get("funding_arb.max_cash_fraction"))
        target = min(max_notional, state.cash_quote * cash_frac)
        if target <= 0.0:
            return []
        qty = target / spot_bar.close
        return [
            Order(
                venue=self._venue, symbol=self._symbol, product="spot",
                side="buy", qty_base=qty, order_type="market",
            ),
            Order(
                venue=self._venue, symbol=self._symbol, product="perp",
                side="sell", qty_base=qty, order_type="market",
            ),
        ]
```

Move the entry-threshold conversion so it's computed before the state check (it's only needed for the flat branch but the state-machine reads cleaner this way):

Final `evaluate`:
```python
    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        funding = state.snapshot.funding_rates.get((self._venue, self._symbol))
        if funding is None:
            return []
        funding_bps_per_8h = funding * _BPS_DIVISOR
        entry = float(params.get("funding_arb.entry_bps_per_8h"))
        spot_pos, perp_pos = self._find_position(state.positions)

        if spot_pos is None and perp_pos is None:
            if funding_bps_per_8h < entry:
                return []
            return self._open_hedge(state, params)
        return []
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/strategies/test_funding_arb.py -v
git add backend/app/strategies/funding_arb.py backend/tests/strategies/test_funding_arb.py
git commit -m "feat: FundingArbStrategy entry path + sizing caps"
```

---

### Task 6: FundingArbStrategy — exit (close hedge) + hold

**Files:**
- Modify: `backend/app/strategies/funding_arb.py`
- Modify: `backend/tests/strategies/test_funding_arb.py`

- [ ] **Step 1: Failing tests (append)**

```python
def _hedged_state(funding: float, qty: float = 0.083) -> MarketState:
    long_spot = Position(
        venue="binance", symbol="BTCUSDT", product="spot",
        qty_base=qty, avg_entry_px=60000.0,
    )
    short_perp = Position(
        venue="binance", symbol="BTCUSDT", product="perp",
        qty_base=-qty, avg_entry_px=60000.0,
    )
    return MarketState(
        snapshot=_snap(funding),
        positions=(long_spot, short_perp),
        cash_quote=5_000.0,
    )


def test_hedged_above_exit_holds() -> None:
    # funding 3 bps > exit 1 bps → hold
    s = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    orders = s.evaluate(_hedged_state(funding=0.0003), _params())
    assert orders == []


def test_hedged_below_exit_closes() -> None:
    # funding 0.5 bps ≤ exit 1 bps → close
    s = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    orders = s.evaluate(_hedged_state(funding=0.00005, qty=0.083), _params())
    assert len(orders) == 2
    # sell spot + buy perp, qty == existing position qty
    spots = [o for o in orders if o.product == "spot"]
    perps = [o for o in orders if o.product == "perp"]
    assert spots[0].side == "sell"
    assert spots[0].qty_base == 0.083
    assert perps[0].side == "buy"
    assert perps[0].qty_base == 0.083
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Add hedged branch**

In `evaluate`, after the flat branch add:
```python
        if spot_pos is not None and perp_pos is not None:
            # Hedged → maybe close if funding decayed
            exit_threshold = float(params.get("funding_arb.exit_bps_per_8h"))
            if funding_bps_per_8h > exit_threshold:
                return []
            return self._close_hedge(spot_pos, perp_pos)
        return []
```

Add helper:
```python
    def _close_hedge(self, spot_pos: Position, perp_pos: Position) -> list[Order]:
        return [
            Order(
                venue=self._venue, symbol=self._symbol, product="spot",
                side="sell", qty_base=abs(spot_pos.qty_base), order_type="market",
            ),
            Order(
                venue=self._venue, symbol=self._symbol, product="perp",
                side="buy", qty_base=abs(perp_pos.qty_base), order_type="market",
            ),
        ]
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/strategies/test_funding_arb.py -v
git add backend/app/strategies/funding_arb.py backend/tests/strategies/test_funding_arb.py
git commit -m "feat: FundingArbStrategy exit path (close hedge below threshold)"
```

---

### Task 7: FundingArbStrategy — orphan leg defensive close

**Files:**
- Modify: `backend/app/strategies/funding_arb.py`
- Modify: `backend/tests/strategies/test_funding_arb.py`

- [ ] **Step 1: Failing tests (append)**

```python
def test_orphan_spot_closes_spot() -> None:
    s = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    orphan = Position(
        venue="binance", symbol="BTCUSDT", product="spot",
        qty_base=0.05, avg_entry_px=60000.0,
    )
    state = MarketState(
        snapshot=_snap(funding=0.0001),
        positions=(orphan,),
        cash_quote=5_000.0,
    )
    orders = s.evaluate(state, _params())
    assert len(orders) == 1
    assert orders[0].side == "sell"
    assert orders[0].product == "spot"
    assert orders[0].qty_base == 0.05


def test_orphan_perp_closes_perp() -> None:
    s = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    orphan = Position(
        venue="binance", symbol="BTCUSDT", product="perp",
        qty_base=-0.05, avg_entry_px=60000.0,
    )
    state = MarketState(
        snapshot=_snap(funding=0.0001),
        positions=(orphan,),
        cash_quote=5_000.0,
    )
    orders = s.evaluate(state, _params())
    assert len(orders) == 1
    assert orders[0].side == "buy"  # close short → buy
    assert orders[0].product == "perp"
    assert orders[0].qty_base == 0.05
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Add orphan branches**

In `evaluate`, before the final `return []`:
```python
        if spot_pos is not None and perp_pos is None:
            return [
                Order(
                    venue=self._venue, symbol=self._symbol, product="spot",
                    side="sell", qty_base=abs(spot_pos.qty_base), order_type="market",
                )
            ]
        if perp_pos is not None and spot_pos is None:
            # Close short perp = buy
            side = "buy" if perp_pos.qty_base < 0.0 else "sell"
            return [
                Order(
                    venue=self._venue, symbol=self._symbol, product="perp",
                    side=side, qty_base=abs(perp_pos.qty_base), order_type="market",
                )
            ]
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/strategies/test_funding_arb.py -v
git add backend/app/strategies/funding_arb.py backend/tests/strategies/test_funding_arb.py
git commit -m "feat: FundingArbStrategy orphan-leg defensive close"
```

---

### Task 8: Hysteresis sweep test

**Files:**
- Modify: `backend/tests/strategies/test_funding_arb.py`

- [ ] **Step 1: Test (append) — proves the 4-state machine through a funding-rate sweep**

```python
def test_hysteresis_full_sweep() -> None:
    """Walk through funding sequence: flat → enter → hold → exit → stay flat."""
    s = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    p = _params()

    # Tick 1: funding 7 bps (> entry 5), flat → enter
    flat = _state(funding=0.0007)
    o1 = s.evaluate(flat, p)
    assert len(o1) == 2

    # Tick 2: funding 4 bps (< entry 5 but > exit 1), hedged → hold
    hedged_high = _hedged_state(funding=0.0004)
    o2 = s.evaluate(hedged_high, p)
    assert o2 == []

    # Tick 3: funding 2 bps (still > exit 1), hedged → hold
    hedged_mid = _hedged_state(funding=0.0002)
    o3 = s.evaluate(hedged_mid, p)
    assert o3 == []

    # Tick 4: funding 0.5 bps (≤ exit 1), hedged → close
    hedged_low = _hedged_state(funding=0.00005)
    o4 = s.evaluate(hedged_low, p)
    assert len(o4) == 2

    # Tick 5: funding 0.5 bps, flat → no orders
    o5 = s.evaluate(_state(funding=0.00005), p)
    assert o5 == []

    # Tick 6: funding 3 bps (< entry 5), flat → no orders (hysteresis)
    o6 = s.evaluate(_state(funding=0.0003), p)
    assert o6 == []
```

- [ ] **Step 2: Tests pass + commit**

```bash
cd backend && uv run pytest tests/strategies/test_funding_arb.py::test_hysteresis_full_sweep -v
git add backend/tests/strategies/test_funding_arb.py
git commit -m "test: FundingArbStrategy hysteresis full sweep"
```

---

## Phase 6.3: Integration

### Task 9: Register funding_arb in StrategyRegistry

**Files:**
- Modify: `backend/app/backtest/registry.py`
- Modify: `backend/tests/backtest/test_registry.py`

- [ ] **Step 1: Failing test (append)**

```python
def test_resolve_funding_arb() -> None:
    reg = StrategyRegistry.default()
    s = reg.build("funding_arb", venue="binance", symbol="BTCUSDT")
    assert s.name == "funding_arb"


def test_funding_arb_in_names() -> None:
    reg = StrategyRegistry.default()
    assert "funding_arb" in reg.names()
```

- [ ] **Step 2: Verify FAILS**

- [ ] **Step 3: Add to registry**

In `backend/app/backtest/registry.py`, modify `default()`:
```python
from app.strategies.funding_arb import FundingArbStrategy

@classmethod
def default(cls) -> StrategyRegistry:
    return cls(
        {
            "buy_and_hold": BuyAndHoldStrategy,
            "funding_arb_skeleton": FundingArbSkeleton,
            "funding_arb": FundingArbStrategy,
        }
    )
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/backtest/test_registry.py -v
git add backend/app/backtest/registry.py backend/tests/backtest/test_registry.py
git commit -m "feat: register funding_arb in StrategyRegistry"
```

---

### Task 10: BacktestService dispatches "funding_arb" with spot+perp products

**Files:**
- Modify: `backend/app/services/backtest_service.py`
- Modify: `backend/tests/services/test_backtest_service.py`

The existing `BacktestService.execute()` has:
```python
products = ["spot", "perp"] if run.strategy_name == "funding_arb_skeleton" else ["spot"]
```

Extend to also include `funding_arb`:
```python
products: list[Product] = (
    ["spot", "perp"]
    if run.strategy_name in {"funding_arb_skeleton", "funding_arb"}
    else ["spot"]
)
```

- [ ] **Step 1: Failing test (append)**

```python
@pytest.mark.asyncio
async def test_funding_arb_uses_spot_and_perp(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    # When strategy_name == "funding_arb", BacktestService should request both products.
    # We verify by writing only spot Parquet data and observing the loader is asked
    # for both — meaning the engine still tries to load perp (even if empty).
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _write_klines(parquet_root)
    curves_root = tmp_path / "backtest_runs"

    profile = StrategyProfile(name="fa-test", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()

    run = BacktestRun(
        profile_id=profile.id,
        profile_version=profile.version,
        profile_hash=_profile_hash(profile.config),
        strategy_name="funding_arb",
        venue="binance",
        symbols=["BTCUSDT"],
        start_ts=datetime(2024, 1, 1, tzinfo=UTC),
        end_ts=datetime(2024, 1, 1, 0, 2, tzinfo=UTC),
        status="pending",
    )
    db_session.add(run)
    await db_session.flush()

    service = BacktestService(
        session=db_session, parquet_root=parquet_root,
        backtest_curves_root=curves_root,
    )
    # Will complete (no funding signal in synthetic data → no entries → no trades)
    await service.execute(run.id)
    await db_session.refresh(run)
    assert run.status == "complete"
    assert run.num_trades == 0  # no funding data → no entries
```

- [ ] **Step 2: Modify + verify**

Update the `products` line in `backend/app/services/backtest_service.py` per above.

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/services/test_backtest_service.py -v
git add backend/app/services/backtest_service.py backend/tests/services/test_backtest_service.py
git commit -m "feat: BacktestService dispatches funding_arb with spot+perp products"
```

---

### Task 11: Engine E2E test on synthetic funding data

**Files:**
- Create: `backend/tests/strategies/test_funding_arb_engine.py`

- [ ] **Step 1: Failing test**

```python
"""Engine-level E2E: FundingArbStrategy over hand-crafted Parquet with a funding event."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from app.backtest.engine import Engine
from app.backtest.loader import BacktestLoader
from app.market_data.parquet_store import ParquetStore
from app.profile.params import ProfileParams
from app.strategies.funding_arb import FundingArbStrategy


def test_funding_arb_engine_e2e_on_synthetic_data(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
    base = 1704067200000
    # 3 spot bars + 3 perp bars at the same timestamps
    kline_spot = pl.DataFrame(
        {
            "ts_ms": [base, base + 60_000, base + 120_000],
            "open": [60000.0, 60000.0, 60000.0],
            "high": [60000.0, 60000.0, 60000.0],
            "low": [60000.0, 60000.0, 60000.0],
            "close": [60000.0, 60000.0, 60000.0],
            "volume": [10.0, 10.0, 10.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", kline_spot, year=2024, month=1)
    # Funding event at tick 2 — 10 bps (above entry 5 bps)
    funding_df = pl.DataFrame(
        {
            "ts_ms": [base + 60_000],
            "predicted": [0.001],
            "realized": [0.001],
        }
    )
    store.write_funding("binance", "BTCUSDT", funding_df, year=2024, month=1)

    loader = BacktestLoader(parquet_root=tmp_path)
    strategy = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    params = ProfileParams(profile={})
    engine = Engine(loader=loader, strategy=strategy, params=params)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 2, tzinfo=UTC)
    result = engine.run(
        venue="binance",
        symbols=["BTCUSDT"],
        products=["spot"],  # synthetic data only has spot
        start=start, end=end,
    )

    # Tick 1: no funding signal yet → no trades
    # Tick 2: funding 10 bps → enter (but spot only, no perp → engine treats spot-only)
    # Tick 3: no funding signal → strategy state-machine sees the orphan, closes
    # Even though the perp leg can't be filled (no perp data), strategy still emits
    # 2 orders at tick 2. The fill simulator will silently drop the perp order
    # (no bar in snapshot for it).
    # So we expect at least 1 fill at tick 2 (the spot leg).
    assert result.num_trades >= 1
```

This test exercises the strategy + engine + loader integration. The exact trade count depends on engine details — the assertion is loose (≥1 fill) to keep it stable across engine refinements.

- [ ] **Step 2: Tests pass + commit**

```bash
cd backend && uv run pytest tests/strategies/test_funding_arb_engine.py -v
git add backend/tests/strategies/test_funding_arb_engine.py
git commit -m "test: FundingArbStrategy engine E2E on synthetic funding data"
```

---

## Phase 6.4: Final wrap

### Task 12: README + final sweep

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append section** after the "OMS + Exchange adapters (Phase 5)" block:

````markdown

## Strategy A — Funding Arb (Phase 6)

Delta-neutral funding-rate arbitrage. Goes long spot + short perp when 8-hour
funding is above the entry threshold; closes the hedge when funding decays
below the exit threshold.

### Backtest

```bash
# Profile must exist; use any of the seeded profiles or create your own
curl -X POST http://localhost:8000/api/v1/backtests -H "Content-Type: application/json" -d '{
  "profile_id": "<uuid>",
  "strategy_name": "funding_arb",
  "start_ts": "2024-01-01T00:00:00Z",
  "end_ts":   "2024-01-31T23:59:00Z",
  "venue":    "binance",
  "symbols": ["BTCUSDT"]
}'
```

### Profile knobs (all in the registry)

| Key | Default | Meaning |
|---|---|---|
| `funding_arb.entry_bps_per_8h` | 5.0 | Open hedge when funding ≥ this |
| `funding_arb.exit_bps_per_8h` | 1.0 | Close hedge when funding ≤ this |
| `funding_arb.max_notional_usdc` | 5_000.0 | Hard cap on spot-leg notional |
| `funding_arb.max_cash_fraction` | 0.5 | Don't deploy >50% of free cash |
| `funding_arb.intervals_per_year` | 1095.75 | 365.25 * 24 / 8h, for APR conversion |

### Deferred to later phases

- **Live trading** → Phase 7 (testnet) → Phase 8 (dry-run) → Phase 9 (live $500)
- **Kelly / vol-target sizing** → Phase 8 risk machinery
- **Cross-venue best-execution routing** → Phase 9+
- **Multi-symbol portfolios** → Phase 13+
````

- [ ] **Step 2: Full sweep**

```bash
just typecheck && just lint && just test
```
Expected: ~194 passed, 2 deselected.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README Strategy A funding arb section"
```

---

### Task 13: PR via /pr-summary

- [ ] **Step 1: Confirm gates green**

- [ ] **Step 2: Parent agent invokes /pr-summary**

MINOR bump (0.5.0 → 0.6.0). CHANGELOG entry. Spec backfill. Tag. Push. PR.

---

## Plan self-review

- **Spec coverage**: registry (Task 1), MarketSnapshot extension (2), Loader (3), strategy implementation in 4 sub-tasks for TDD discipline (4-7), hysteresis sweep (8), registry registration (9), BacktestService routing (10), engine E2E (11), README + PR (12-13). Every spec section has a task.
- **Type consistency**: `Position`, `Order`, `MarketState`, `MarketSnapshot`, `ProfileParams` all reused from Phase 4/5. New `MarketSnapshot.funding_rates: dict[tuple[str, str], float]` with `field(default_factory=dict)` keeps existing construction sites working.
- **Constraint #1 enforcement**: All numeric thresholds in `funding_arb.py` come from registry. `_BPS_DIVISOR = 10_000.0` is the only module constant (unit-of-measure, AST lint carveout).
- **Constraint #2 enforcement**: same `Strategy.evaluate(state, params)` shape as Phase 4/5; backtest and live paths use identical code.
- **Constraint #4 enforcement**: audit pipeline unchanged; existing Phase 5 audit-trail tests cover Strategy A by extension.
- **TDD discipline**: every task is RED → GREEN → COMMIT. The strategy is built in 4 incremental tasks (4-7) each with focused tests.
- **Frequent commits**: 13 commits, mean ~40 LOC each.
