# Cryptobot Phase 6 — Strategy A (Funding Arb) Design Spec

**Date**: 2026-05-24
**Status**: approved (autonomous mode — user delegated design defaults)
**Phase**: 6 of the cryptobot build
**Blocks**: Phase 7 (testnet end-to-end), Phase 8 (dry-run), Phase 9 (live $500)
**Revision history**: v1 — initial. PR #8.

## Goal

Ship the **first real strategy**: a delta-neutral funding-rate arbitrage that goes long spot + short perp when 8-hour funding is sufficiently positive, holds while it stays above the exit threshold, and unwinds when funding decays. The strategy is a pure `Strategy.evaluate(state, params) → list[Order]` function — same shape Phase 4 BuyAndHold + FundingArbSkeleton use, same OMS integration from Phase 5.

## Non-goals

- **Live trading on testnet/mainnet** → Phase 7+. Phase 6 ships a working strategy that backtests against Phase 3 historical data and passes paper-trading dispatch.
- **Kelly / Bayesian sizing, vol targeting, drawdown brake** → Phase 8 risk machinery. Phase 6 sizes via a profile-registry `max_notional_usdc` knob and a fixed fraction-of-cash cap.
- **Cross-venue best-execution routing** → Phase 9+. Phase 6 commits to a configured `funding_arb.venue` (single venue per strategy instance; default Binance perp + Binance spot).
- **Strategy B (factor portfolio)** → Phase 14+.
- **Predictive funding modeling, regime detection, LLM overlay** → Phase 14+.
- **Multi-symbol portfolios** → Phase 13+. Phase 6 trades ONE symbol per strategy instance (configurable, default BTCUSDT).

## Architecture

Strategy A is a pure function. Inputs:
1. `MarketState` (positions + cash + market snapshot) — Phase 4 contract.
2. `ProfileParams` accessor over the registry — Phase 1+2 contract.

Output: `list[Order]` — Phase 4 contract. Consumed by:
- Backtest engine (Phase 4) for historical sim
- OMS (Phase 5) for paper / live dispatch

### New requirement: funding rate in `MarketSnapshot`

Strategy A's entry/exit decision depends on the **current funding rate** for the perp leg. The Phase 4 `MarketSnapshot` carries `bars` (OHLCV) only. Phase 6 extends:

```python
@dataclass(frozen=True)
class MarketSnapshot:
    ts_ms: int
    bars: dict[tuple[str, str, Product], Bar]
    funding_rates: dict[tuple[str, str], float]   # (venue, symbol) → realized rate at ts_ms
```

`funding_rates` is populated by:
- Backtest `BacktestLoader` — already loads funding Parquet for the `FundingLedger`; extend to also surface per-tick rates into the snapshot.
- Future live state-fetcher (Phase 7+) — fetches via `Exchange.fetch_funding_rate()`. Phase 6 adds the Protocol method but only the paper adapter implements it (paper returns a configurable rate).

If no funding rate is available for a venue/symbol at the tick (no row in funding Parquet at that ts), the strategy treats it as `0.0` (neutral — neither entry nor exit signal).

### Entry / exit logic

The strategy is a 4-state machine based on `MarketState.positions`:

| Current state | Signal | Action |
|---|---|---|
| Flat (no position on venue/symbol) | `funding_rate ≥ entry_threshold` | Open hedge pair (buy spot + sell perp), sized by `funding_arb.max_notional_usdc` |
| Flat | `funding_rate < entry_threshold` | Hold (no orders) |
| Hedged (spot long + perp short, equal magnitude) | `funding_rate ≤ exit_threshold` | Close hedge (sell spot + buy perp, exact qty match) |
| Hedged | `funding_rate > exit_threshold` | Hold (no orders) |
| Spot-only (orphan leg after partial fill) | any | Close the spot (defensive — should not happen in normal flow; logs warning via audit) |
| Perp-only (orphan leg) | any | Close the perp |

Entry threshold > exit threshold (hysteresis to avoid churn). Both registry-driven; defaults:
- `funding_arb.entry_bps_per_8h = 5.0` (≈ +22.8% APR break-even)
- `funding_arb.exit_bps_per_8h = 1.0` (≈ +4.6% APR)

Funding rates in Parquet are typically per-interval (8h on Binance, 1h on HL). Strategy A annualises by multiplying by `funding_arb.intervals_per_year` from the profile registry (default 365.25 × 24 / 8 = 1095.75 for Binance 8h).

### Sizing

Phase 6 sizing is simple:
```python
target_notional = min(
    funding_arb.max_notional_usdc,
    state.cash_quote * funding_arb.max_cash_fraction,
)
qty_spot = target_notional / spot_bar.close
qty_perp = qty_spot   # delta-neutral
```

Profile keys (numeric):
- `funding_arb.max_notional_usdc = 5_000.0` (matches HLP scale; tunable)
- `funding_arb.max_cash_fraction = 0.5` (don't deploy >50% of free cash to one leg)

Phase 8 will replace this with Kelly + vol targeting. The interface stays the same.

### Strategy initialization

```python
class FundingArbStrategy:
    name = "funding_arb"

    def __init__(self, *, venue: str, symbol: str) -> None:
        ...

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        ...
```

The `venue` + `symbol` are construction-time constants (one instance per market). Multi-symbol portfolios are Phase 13+.

## Components

```
app/strategies/funding_arb.py       # main strategy file
app/strategies/__init__.py          # already exists from Phase 1+2 — just keep
app/backtest/loader.py              # MODIFY: populate funding_rates into MarketSnapshot
app/backtest/state.py               # MODIFY: add funding_rates field to MarketSnapshot
app/exchanges/base.py               # MODIFY: add Exchange.fetch_funding_rate Protocol method
app/exchanges/paper.py              # MODIFY: implement fetch_funding_rate
app/backtest/registry.py            # MODIFY: register "funding_arb" alongside existing validators
```

### `MarketSnapshot` migration concern

Adding a required field to a frozen dataclass is a breaking change for every construction site. The cleanest fix:
- Add `funding_rates: dict[tuple[str, str], float] = field(default_factory=dict)` with a default.
- Existing construction sites (Phase 4 engine + paper-fill tests + audit-trail tests) keep working unchanged.
- Phase 6 tests for FundingArb explicitly populate the field.

Per Constraint #1, no numeric literals in `app/strategies/funding_arb.py`. All thresholds via `params.get(...)`.

## Profile registry additions

Numeric (`PROFILE_SCOPED_DEFAULTS`):
```
funding_arb.entry_bps_per_8h            5.0
funding_arb.exit_bps_per_8h             1.0
funding_arb.max_notional_usdc           5_000.0
funding_arb.max_cash_fraction           0.5
funding_arb.intervals_per_year          1095.75    # 365.25 * 24 / 8
```

String (`PROFILE_SCOPED_STRING_DEFAULTS`):
```
funding_arb.default_venue               "binance"
funding_arb.default_symbol              "BTCUSDT"
```

(These are convenience defaults; per-instance config takes precedence via constructor args.)

## Database / migrations

**None.** Strategy A reuses:
- Phase 1+2 `StrategyProfile` (for params)
- Phase 4 `BacktestRun` (when backtested)
- Phase 5 `DecisionAuditEntry` (when OMS-dispatched)

No new tables.

## API

**None new in Phase 6.** Strategy A is invoked through existing endpoints:
- Backtest: `POST /api/v1/backtests {strategy_name: "funding_arb", ...}` — requires `StrategyRegistry.default()` to know "funding_arb"
- Live dispatch: through `OMS.dispatch(orders=strategy.evaluate(...), ...)` from a future live runner (Phase 7)

The `StrategyRegistry` from Phase 4 currently knows `buy_and_hold` and `funding_arb_skeleton`. Phase 6 adds `funding_arb`.

## Testing strategy

~15 new tests:

**Unit (pure logic, fast)**:
- `test_funding_arb_flat_under_threshold_no_orders` — flat + funding 2 bps (< entry 5 bps) → empty list
- `test_funding_arb_flat_above_threshold_opens_hedge` — flat + funding 7 bps → 2 orders (buy spot, sell perp)
- `test_funding_arb_hedged_above_exit_holds` — hedged + funding 3 bps (> exit 1 bps) → empty list
- `test_funding_arb_hedged_below_exit_closes` — hedged + funding 0.5 bps → 2 orders (sell spot, buy perp), qty matching existing
- `test_funding_arb_sizing_caps_at_max_notional` — large cash + entry signal → qty = max_notional / px
- `test_funding_arb_sizing_caps_at_cash_fraction` — small cash + entry signal → qty = (cash * fraction) / px
- `test_funding_arb_no_funding_data_for_venue_no_orders` — flat + funding_rates missing → empty (treats as 0)
- `test_funding_arb_orphan_spot_closes_spot` — only spot position, no perp → 1 order (sell spot)
- `test_funding_arb_orphan_perp_closes_perp` — only perp position, no spot → 1 order (buy perp)
- `test_funding_arb_hysteresis_no_churn` — sweep funding from 7 → 4 → 2 → 0.5 → 0.5 → 2, count orders. Expect: enter at 7, hold at 4, hold at 2, exit at 0.5, hold flat at 0.5, hold flat at 2 (< entry 5).

**Integration (engine end-to-end)**:
- `test_funding_arb_engine_e2e_on_synthetic_data` — hand-crafted Parquet kline + funding data; 3-period sequence (no entry → entry → exit); equity curve matches expected funding collection

**Strategy registry**:
- `test_strategy_registry_resolves_funding_arb` — `StrategyRegistry.default().build("funding_arb", ...)` returns instance with name == "funding_arb"

**API**:
- `test_post_backtest_accepts_funding_arb` — POST `/api/v1/backtests {strategy_name: "funding_arb", ...}` against Phase 3 Parquet data returns 202

**Audit (Constraint #4)**:
- (covered by Phase 5's existing audit-trail test — Strategy A doesn't change the audit pipeline)

**AST literal lint**:
- The existing scan covers `backend/app/strategies/**`, so `funding_arb.py` is automatically in scope. Test `test_lint_catches_injected_literal` already verifies the mechanism. No new lint test needed.

## Edge cases

- **Funding rate = exactly entry_threshold** → enter (≥ comparison)
- **Funding rate = exactly exit_threshold** → exit (≤ comparison)
- **Cash = 0** → sizing yields 0 qty → no orders (the `if qty == 0: return []` short-circuit)
- **Spot price = 0** (impossible in real data, but defensive) → no orders
- **Profile lacks one of the registry keys** → ProfileParams default fallback (Constraint #3) kicks in
- **Position with non-zero perp but zero spot** (orphan after fail) → close perp only
- **Hedged but qty mismatch >5%** → Phase 5 reconciler catches this BEFORE the strategy runs; strategy sees the halt-state and emits no orders

## Definition of done (gate to Phase 7)

- ~194 tests total (Phase 5 final 179) — mypy --strict + ruff + AST lint clean
- All 10 unit tests pass with synthetic states
- 1 engine E2E test passes with synthetic Parquet
- `StrategyRegistry.default()` knows "funding_arb" + tests verify
- POST `/api/v1/backtests {strategy_name: "funding_arb"}` works end-to-end (existing endpoint accepts the new name)
- New `MarketSnapshot.funding_rates` field with `default_factory=dict` — backward-compatible
- `BacktestLoader.iter_snapshots` populates `funding_rates` from Parquet
- Profile registry has 5 numeric + 2 string keys for `funding_arb.*`
- No literals in `backend/app/strategies/funding_arb.py` (AST lint enforced)
- README has "Strategy A — Funding Arb (Phase 6)" section with: registry knobs, how to backtest, what's deferred

## Out of scope (deferred)

- Real testnet / live trading → Phase 7
- Kelly / Bayesian sizing → Phase 8
- Drawdown brake / vol targeting / kill switch automation → Phase 8
- Multi-symbol portfolio → Phase 13
- LLM overlay / regime detection → Phase 14+
- Cross-venue routing → Phase 9+
- WebSocket fills → Phase 7+
- Composite IC scoring (Strategy B style) → Phase 14+

## References

- `docs/superpowers/research/cryptobot-strategy-architecture.md` — funding arb economics, fee tables, HLP benchmark
- `docs/superpowers/specs/2026-05-24-cryptobot-backtester-design.md` — backtest engine + `Strategy` Protocol
- `docs/superpowers/specs/2026-05-24-cryptobot-oms-design.md` — OMS dispatch + audit
- `backend/app/backtest/strategies/funding_arb_skeleton.py` — Phase 4 validator (Strategy A's structural ancestor)
- `backend/app/profile/{defaults, params}.py` — registry to extend
- `backend/app/backtest/loader.py` — extend to populate `funding_rates`
- `backend/app/backtest/state.py` — `MarketSnapshot` extension
- `backend/app/exchanges/{base, paper}.py` — Protocol + paper adapter extension
- `backend/app/backtest/registry.py` — register "funding_arb"
