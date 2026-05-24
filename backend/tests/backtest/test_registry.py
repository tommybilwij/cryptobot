"""Tests for backtest strategy registry — name → Strategy factory."""

from __future__ import annotations

import pytest

from app.backtest.registry import StrategyRegistry, UnknownStrategy


def test_resolve_buy_and_hold() -> None:
    reg = StrategyRegistry.default()
    s = reg.build("buy_and_hold", venue="binance", symbol="BTCUSDT")
    assert s.name == "buy_and_hold"


def test_resolve_funding_arb_skeleton() -> None:
    reg = StrategyRegistry.default()
    s = reg.build("funding_arb_skeleton", venue="binance", symbol="BTCUSDT")
    assert s.name == "funding_arb_skeleton"


def test_unknown_strategy_raises() -> None:
    reg = StrategyRegistry.default()
    with pytest.raises(UnknownStrategy):
        reg.build("does_not_exist", venue="binance", symbol="BTCUSDT")


def test_names_returns_registered_strategies() -> None:
    reg = StrategyRegistry.default()
    names = reg.names()
    assert "buy_and_hold" in names
    assert "funding_arb_skeleton" in names
    assert "funding_arb" in names


def test_resolve_funding_arb() -> None:
    reg = StrategyRegistry.default()
    s = reg.build("funding_arb", venue="binance", symbol="BTCUSDT")
    assert s.name == "funding_arb"
