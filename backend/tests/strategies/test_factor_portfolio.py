"""Tests for FactorPortfolioStrategy."""

from __future__ import annotations

from app.backtest.state import Bar, MarketSnapshot, MarketState, Position
from app.profile.params import ProfileParams
from app.strategies.factor_portfolio import FactorPortfolioStrategy


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def _bar(symbol: str, close: float) -> Bar:
    return Bar(
        ts_ms=1,
        venue="binance",
        symbol=symbol,
        product="spot",
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100.0,
    )


def _snap(symbols_with_funding: dict[str, float]) -> MarketSnapshot:
    bars: dict[tuple[str, str, str], Bar] = {}
    for symbol in symbols_with_funding:
        bars[("binance", symbol, "spot")] = _bar(symbol, 100.0)
    funding_rates = {("binance", symbol): rate for symbol, rate in symbols_with_funding.items()}
    return MarketSnapshot(ts_ms=1, bars=bars, funding_rates=funding_rates)  # type: ignore[arg-type]


def test_empty_universe_emits_no_orders() -> None:
    s = FactorPortfolioStrategy(venue="binance", universe=[])
    state = MarketState(
        snapshot=MarketSnapshot(ts_ms=1, bars={}),
        positions=(),
        cash_quote=10_000.0,
    )
    assert s.evaluate(state, _params()) == []


def test_selects_top_decile_from_universe() -> None:
    """10 symbols, top_decile_pct=0.1 -> 1 symbol = top scorer."""
    universe = [f"SYM{i:02d}" for i in range(10)]
    s = FactorPortfolioStrategy(venue="binance", universe=universe)
    funding_map = {sym: 0.0001 * (i + 1) for i, sym in enumerate(universe)}
    state = MarketState(
        snapshot=_snap(funding_map),
        positions=(),
        cash_quote=10_000.0,
    )
    orders = s.evaluate(state, _params())
    # 1 buy order for the top scorer (SYM09 has highest funding).
    buys = [o for o in orders if o.side == "buy"]
    assert len(buys) == 1
    assert buys[0].symbol == "SYM09"


def test_no_funding_data_features_zero() -> None:
    """Without funding rates, scoring returns 0 -> at most one neutral pick."""
    universe = ["AAA", "BBB"]
    s = FactorPortfolioStrategy(venue="binance", universe=universe)
    bars = {("binance", sym, "spot"): _bar(sym, 100.0) for sym in universe}
    state = MarketState(
        snapshot=MarketSnapshot(ts_ms=1, bars=bars, funding_rates={}),
        positions=(),
        cash_quote=10_000.0,
    )
    orders = s.evaluate(state, _params())
    # All scores tie at 0; top_decile selects 1 (min). Order count <= 1.
    assert len(orders) <= 1


def test_skips_symbols_without_bars() -> None:
    """Symbol in universe but no bar in snapshot -> no order."""
    universe = ["AAA"]
    s = FactorPortfolioStrategy(venue="binance", universe=universe)
    state = MarketState(
        snapshot=MarketSnapshot(ts_ms=1, bars={}, funding_rates={("binance", "AAA"): 0.001}),
        positions=(),
        cash_quote=10_000.0,
    )
    orders = s.evaluate(state, _params())
    assert orders == []


def test_closes_stale_long_position() -> None:
    """Existing long for symbol no longer in top decile -> close order emitted."""
    universe = ["BBB", "CCC"]
    s = FactorPortfolioStrategy(venue="binance", universe=universe)
    # Stale long in AAA (not in universe).
    stale = Position(
        venue="binance",
        symbol="AAA",
        product="spot",
        qty_base=10.0,
        avg_entry_px=100.0,
    )
    funding_map = {"BBB": 0.0001, "CCC": 0.0002}
    state = MarketState(
        snapshot=_snap(funding_map),
        positions=(stale,),
        cash_quote=10_000.0,
    )
    orders = s.evaluate(state, _params())
    sells = [o for o in orders if o.symbol == "AAA" and o.side == "sell"]
    assert len(sells) == 1
    assert sells[0].qty_base == 10.0


def test_registry_resolves_factor_portfolio() -> None:
    from app.backtest.registry import StrategyRegistry

    reg = StrategyRegistry.default()
    s = reg.build("factor_portfolio", venue="binance", universe=["BTCUSDT"])
    assert s.name == "factor_portfolio"
