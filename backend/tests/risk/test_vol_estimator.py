"""Tests for RollingVolEstimator."""

from __future__ import annotations

from app.risk.vol_estimator import RollingVolEstimator


def test_empty_returns_zero() -> None:
    e = RollingVolEstimator(window_bars=30)
    assert e.annualised_vol(venue="binance", symbol="BTCUSDT") == 0.0


def test_constant_prices_zero_vol() -> None:
    e = RollingVolEstimator(window_bars=30)
    e.seed_from_bars("binance", "BTCUSDT", [60000.0] * 20)
    vol = e.annualised_vol(venue="binance", symbol="BTCUSDT")
    assert vol == 0.0


def test_alternating_prices_positive_vol() -> None:
    e = RollingVolEstimator(window_bars=30)
    # Up 1%, down 1%, repeat.
    prices = []
    p = 60000.0
    for i in range(20):
        p = p * (1.01 if i % 2 == 0 else 0.99)
        prices.append(p)
    e.seed_from_bars("binance", "BTCUSDT", prices)
    vol = e.annualised_vol(venue="binance", symbol="BTCUSDT")
    assert vol > 0.0


def test_window_caps_history() -> None:
    e = RollingVolEstimator(window_bars=5)
    e.seed_from_bars("binance", "BTCUSDT", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    # Only last 5 (3,4,5,6,7) kept — still produces a non-zero vol estimate.
    assert e.annualised_vol(venue="binance", symbol="BTCUSDT") > 0.0
