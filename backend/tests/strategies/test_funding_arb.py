"""Tests for FundingArbStrategy — Phase 6 real strategy."""

from __future__ import annotations

from app.backtest.state import Bar, MarketSnapshot, MarketState, Position
from app.profile.params import ProfileParams
from app.strategies.funding_arb import FundingArbStrategy


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def _snap(funding: float = 0.0) -> MarketSnapshot:
    spot = Bar(
        ts_ms=1,
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        open=60000.0,
        high=60010.0,
        low=59990.0,
        close=60000.0,
        volume=10.0,
    )
    perp = Bar(
        ts_ms=1,
        venue="binance",
        symbol="BTCUSDT",
        product="perp",
        open=60000.0,
        high=60010.0,
        low=59990.0,
        close=60000.0,
        volume=10.0,
    )
    return MarketSnapshot(
        ts_ms=1,
        bars={
            ("binance", "BTCUSDT", "spot"): spot,
            ("binance", "BTCUSDT", "perp"): perp,
        },
        funding_rates={("binance", "BTCUSDT"): funding},
    )


def _state(
    positions: tuple[Position, ...] = (),
    cash: float = 10_000.0,
    funding: float = 0.0,
) -> MarketState:
    return MarketState(snapshot=_snap(funding), positions=positions, cash_quote=cash)


def test_flat_under_threshold_no_orders() -> None:
    # entry threshold default 8.0 bps; here 7 bps → no entry
    s = FundingArbStrategy(venue="binance", symbols=["BTCUSDT"])
    orders = s.evaluate(_state(funding=0.0007), _params())
    assert orders == []


def test_no_funding_data_for_venue_no_orders() -> None:
    s = FundingArbStrategy(venue="binance", symbols=["BTCUSDT"])
    state = MarketState(
        snapshot=MarketSnapshot(
            ts_ms=1,
            bars={
                ("binance", "BTCUSDT", "spot"): Bar(
                    ts_ms=1,
                    venue="binance",
                    symbol="BTCUSDT",
                    product="spot",
                    open=60000.0,
                    high=60000.0,
                    low=60000.0,
                    close=60000.0,
                    volume=1.0,
                ),
                ("binance", "BTCUSDT", "perp"): Bar(
                    ts_ms=1,
                    venue="binance",
                    symbol="BTCUSDT",
                    product="perp",
                    open=60000.0,
                    high=60000.0,
                    low=60000.0,
                    close=60000.0,
                    volume=1.0,
                ),
            },
            funding_rates={},
        ),
        positions=(),
        cash_quote=10_000.0,
    )
    orders = s.evaluate(state, _params())
    assert orders == []


def test_flat_above_threshold_opens_hedge() -> None:
    # 10 bps > 8 entry; cash 10k, max_notional 5k, max_cash_fraction 0.5 → 5k notional
    # qty = 5000 / 60000 ≈ 0.08333
    s = FundingArbStrategy(venue="binance", symbols=["BTCUSDT"])
    orders = s.evaluate(_state(funding=0.0010), _params())
    assert len(orders) == 2
    spots = [o for o in orders if o.product == "spot"]
    perps = [o for o in orders if o.product == "perp"]
    assert len(spots) == 1 and len(perps) == 1
    assert spots[0].side == "buy"
    assert perps[0].side == "sell"
    assert spots[0].qty_base == perps[0].qty_base  # delta-neutral
    assert spots[0].qty_base > 0


def test_sizing_caps_at_max_notional() -> None:
    s = FundingArbStrategy(venue="binance", symbols=["BTCUSDT"])
    # 100k cash; max_notional 5000 wins over 50000 cash_fraction
    orders = s.evaluate(_state(cash=100_000.0, funding=0.0010), _params())
    expected_qty = 5000.0 / 60000.0
    assert orders[0].qty_base == expected_qty


def test_sizing_caps_at_cash_fraction() -> None:
    s = FundingArbStrategy(venue="binance", symbols=["BTCUSDT"])
    # 1000 cash; max_cash_fraction 0.5 → 500 notional wins over 5000
    orders = s.evaluate(_state(cash=1_000.0, funding=0.0010), _params())
    expected_qty = 500.0 / 60000.0
    assert orders[0].qty_base == expected_qty


def _hedged_state(funding: float, qty: float = 0.083) -> MarketState:
    long_spot = Position(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        qty_base=qty,
        avg_entry_px=60000.0,
    )
    short_perp = Position(
        venue="binance",
        symbol="BTCUSDT",
        product="perp",
        qty_base=-qty,
        avg_entry_px=60000.0,
    )
    return MarketState(
        snapshot=_snap(funding),
        positions=(long_spot, short_perp),
        cash_quote=5_000.0,
    )


def test_hedged_above_exit_holds() -> None:
    # funding 5 bps > exit 4 bps → hold
    s = FundingArbStrategy(venue="binance", symbols=["BTCUSDT"])
    orders = s.evaluate(_hedged_state(funding=0.0005), _params())
    assert orders == []


def test_hedged_below_exit_closes() -> None:
    # funding 2 bps ≤ exit 4 bps → close
    s = FundingArbStrategy(venue="binance", symbols=["BTCUSDT"])
    orders = s.evaluate(_hedged_state(funding=0.0002, qty=0.083), _params())
    assert len(orders) == 2
    spots = [o for o in orders if o.product == "spot"]
    perps = [o for o in orders if o.product == "perp"]
    assert spots[0].side == "sell"
    assert spots[0].qty_base == 0.083
    assert perps[0].side == "buy"
    assert perps[0].qty_base == 0.083


def test_orphan_spot_closes_spot() -> None:
    s = FundingArbStrategy(venue="binance", symbols=["BTCUSDT"])
    orphan = Position(
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        qty_base=0.05,
        avg_entry_px=60000.0,
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
    s = FundingArbStrategy(venue="binance", symbols=["BTCUSDT"])
    orphan = Position(
        venue="binance",
        symbol="BTCUSDT",
        product="perp",
        qty_base=-0.05,
        avg_entry_px=60000.0,
    )
    state = MarketState(
        snapshot=_snap(funding=0.0001),
        positions=(orphan,),
        cash_quote=5_000.0,
    )
    orders = s.evaluate(state, _params())
    assert len(orders) == 1
    assert orders[0].side == "buy"
    assert orders[0].product == "perp"
    assert orders[0].qty_base == 0.05


def test_hysteresis_full_sweep() -> None:
    """Walk through funding sequence: flat → enter → hold → exit → stay flat."""
    s = FundingArbStrategy(venue="binance", symbols=["BTCUSDT"])
    p = _params()

    # Tick 1: funding 10 bps (> entry 8), flat → enter
    o1 = s.evaluate(_state(funding=0.0010), p)
    assert len(o1) == 2

    # Tick 2: funding 7 bps (< entry 8 but > exit 4), hedged → hold
    o2 = s.evaluate(_hedged_state(funding=0.0007), p)
    assert o2 == []

    # Tick 3: funding 5 bps (still > exit 4), hedged → hold
    o3 = s.evaluate(_hedged_state(funding=0.0005), p)
    assert o3 == []

    # Tick 4: funding 2 bps (≤ exit 4), hedged → close
    o4 = s.evaluate(_hedged_state(funding=0.0002), p)
    assert len(o4) == 2

    # Tick 5: funding 2 bps, flat → no orders (below entry)
    o5 = s.evaluate(_state(funding=0.0002), p)
    assert o5 == []

    # Tick 6: funding 6 bps (< entry 8), flat → no orders (hysteresis)
    o6 = s.evaluate(_state(funding=0.0006), p)
    assert o6 == []


def test_multi_symbol_emits_orders_per_symbol() -> None:
    """Strategy across 2 symbols should emit orders for each (if both meet threshold)."""
    s = FundingArbStrategy(venue="binance", symbols=["BTCUSDT", "ETHUSDT"])
    spot_btc = Bar(
        ts_ms=1,
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        open=60000.0,
        high=60010.0,
        low=59990.0,
        close=60000.0,
        volume=10.0,
    )
    perp_btc = Bar(
        ts_ms=1,
        venue="binance",
        symbol="BTCUSDT",
        product="perp",
        open=60000.0,
        high=60010.0,
        low=59990.0,
        close=60000.0,
        volume=10.0,
    )
    spot_eth = Bar(
        ts_ms=1,
        venue="binance",
        symbol="ETHUSDT",
        product="spot",
        open=3000.0,
        high=3010.0,
        low=2990.0,
        close=3000.0,
        volume=100.0,
    )
    perp_eth = Bar(
        ts_ms=1,
        venue="binance",
        symbol="ETHUSDT",
        product="perp",
        open=3000.0,
        high=3010.0,
        low=2990.0,
        close=3000.0,
        volume=100.0,
    )
    snap = MarketSnapshot(
        ts_ms=1,
        bars={
            ("binance", "BTCUSDT", "spot"): spot_btc,
            ("binance", "BTCUSDT", "perp"): perp_btc,
            ("binance", "ETHUSDT", "spot"): spot_eth,
            ("binance", "ETHUSDT", "perp"): perp_eth,
        },
        funding_rates={
            ("binance", "BTCUSDT"): 0.0010,
            ("binance", "ETHUSDT"): 0.0010,
        },
    )
    state = MarketState(snapshot=snap, positions=(), cash_quote=10_000.0)
    orders = s.evaluate(state, _params())
    # 2 symbols × (spot + perp) = 4 orders
    assert len(orders) == 4
    symbols_seen = {o.symbol for o in orders}
    assert symbols_seen == {"BTCUSDT", "ETHUSDT"}


def test_multi_symbol_splits_cash() -> None:
    """With 2 symbols, each gets ~half the cash allocation."""
    s = FundingArbStrategy(venue="binance", symbols=["BTCUSDT", "ETHUSDT"])
    spot_btc = Bar(
        ts_ms=1,
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        open=60000.0,
        high=60010.0,
        low=59990.0,
        close=60000.0,
        volume=10.0,
    )
    perp_btc = Bar(
        ts_ms=1,
        venue="binance",
        symbol="BTCUSDT",
        product="perp",
        open=60000.0,
        high=60010.0,
        low=59990.0,
        close=60000.0,
        volume=10.0,
    )
    spot_eth = Bar(
        ts_ms=1,
        venue="binance",
        symbol="ETHUSDT",
        product="spot",
        open=3000.0,
        high=3010.0,
        low=2990.0,
        close=3000.0,
        volume=100.0,
    )
    perp_eth = Bar(
        ts_ms=1,
        venue="binance",
        symbol="ETHUSDT",
        product="perp",
        open=3000.0,
        high=3010.0,
        low=2990.0,
        close=3000.0,
        volume=100.0,
    )
    snap = MarketSnapshot(
        ts_ms=1,
        bars={
            ("binance", "BTCUSDT", "spot"): spot_btc,
            ("binance", "BTCUSDT", "perp"): perp_btc,
            ("binance", "ETHUSDT", "spot"): spot_eth,
            ("binance", "ETHUSDT", "perp"): perp_eth,
        },
        funding_rates={
            ("binance", "BTCUSDT"): 0.0010,
            ("binance", "ETHUSDT"): 0.0010,
        },
    )
    # Small cash (2000) → each symbol gets 1000 → at 0.5 fraction → 500 notional / px
    state = MarketState(snapshot=snap, positions=(), cash_quote=2_000.0)
    orders = s.evaluate(state, _params())
    btc_orders = [o for o in orders if o.symbol == "BTCUSDT"]
    eth_orders = [o for o in orders if o.symbol == "ETHUSDT"]
    btc_notional = btc_orders[0].qty_base * 60_000.0
    eth_notional = eth_orders[0].qty_base * 3_000.0
    # Each should be ~500 (1000 cash * 0.5 fraction); allow small tolerance
    assert 400.0 <= btc_notional <= 600.0
    assert 400.0 <= eth_notional <= 600.0
