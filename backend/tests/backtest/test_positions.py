"""Tests for PositionBook — tracks open positions, applies fills, marks to market."""

from __future__ import annotations

from app.backtest.orders import Fill, Order
from app.backtest.positions import PositionBook
from app.backtest.state import Bar, MarketSnapshot


def _market_buy(qty: float, venue: str = "binance", symbol: str = "BTCUSDT") -> Order:
    return Order(
        venue=venue,
        symbol=symbol,
        product="spot",
        side="buy",
        qty_base=qty,
        order_type="market",
    )


def _market_sell(qty: float, venue: str = "binance", symbol: str = "BTCUSDT") -> Order:
    return Order(
        venue=venue,
        symbol=symbol,
        product="spot",
        side="sell",
        qty_base=qty,
        order_type="market",
    )


def test_open_long_from_empty() -> None:
    book = PositionBook()
    book.apply([Fill(ts_ms=0, order=_market_buy(0.5), fill_px=60000.0, fee_quote=3.0)])
    positions = book.snapshot()
    assert len(positions) == 1
    assert positions[0].qty_base == 0.5
    assert positions[0].avg_entry_px == 60000.0


def test_add_to_long_updates_avg_entry() -> None:
    book = PositionBook()
    book.apply([Fill(ts_ms=0, order=_market_buy(0.5), fill_px=60000.0, fee_quote=0.0)])
    book.apply([Fill(ts_ms=0, order=_market_buy(0.5), fill_px=62000.0, fee_quote=0.0)])
    positions = book.snapshot()
    assert positions[0].qty_base == 1.0
    assert positions[0].avg_entry_px == 61000.0


def test_partial_close_reduces_qty_keeps_avg_entry() -> None:
    book = PositionBook()
    book.apply([Fill(ts_ms=0, order=_market_buy(1.0), fill_px=60000.0, fee_quote=0.0)])
    book.apply([Fill(ts_ms=0, order=_market_sell(0.4), fill_px=61000.0, fee_quote=0.0)])
    positions = book.snapshot()
    assert positions[0].qty_base == 0.6
    assert positions[0].avg_entry_px == 60000.0


def test_full_close_removes_position() -> None:
    book = PositionBook()
    book.apply([Fill(ts_ms=0, order=_market_buy(1.0), fill_px=60000.0, fee_quote=0.0)])
    book.apply([Fill(ts_ms=0, order=_market_sell(1.0), fill_px=61000.0, fee_quote=0.0)])
    assert book.snapshot() == ()


def test_mark_to_market_uses_close() -> None:
    book = PositionBook()
    book.apply([Fill(ts_ms=0, order=_market_buy(1.0), fill_px=60000.0, fee_quote=0.0)])
    bar = Bar(
        ts_ms=1,
        venue="binance",
        symbol="BTCUSDT",
        product="spot",
        open=61000.0,
        high=61500.0,
        low=60500.0,
        close=61200.0,
        volume=10.0,
    )
    snap = MarketSnapshot(ts_ms=1, bars={("binance", "BTCUSDT", "spot"): bar})
    assert book.mark_to_market(snap) == 61200.0  # 1.0 BTC * 61200


def test_short_perp_mark_to_market_is_negative_notional() -> None:
    book = PositionBook()
    sell = Order(
        venue="binance",
        symbol="BTCUSDT",
        product="perp",
        side="sell",
        qty_base=0.5,
        order_type="market",
    )
    book.apply([Fill(ts_ms=0, order=sell, fill_px=60000.0, fee_quote=0.0)])
    bar = Bar(
        ts_ms=1,
        venue="binance",
        symbol="BTCUSDT",
        product="perp",
        open=61000.0,
        high=61000.0,
        low=61000.0,
        close=61000.0,
        volume=1.0,
    )
    snap = MarketSnapshot(ts_ms=1, bars={("binance", "BTCUSDT", "perp"): bar})
    # short 0.5 perp marked at 61000 → -30500 (mark value of liability)
    assert book.mark_to_market(snap) == -30500.0
