"""Strategy registry — name → Strategy factory.

The API endpoint validates ``strategy_name`` against this registry; the
worker job looks it up to construct the strategy instance.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.backtest.strategies.base import Strategy
from app.backtest.strategies.buy_and_hold import BuyAndHoldStrategy
from app.backtest.strategies.funding_arb_skeleton import FundingArbSkeleton
from app.strategies.factor_portfolio import FactorPortfolioStrategy
from app.strategies.funding_arb import FundingArbStrategy


class UnknownStrategy(KeyError):
    """Raised when a strategy_name isn't registered."""


class StrategyRegistry:
    def __init__(self, factories: dict[str, Callable[..., Strategy]]) -> None:
        self._factories = factories

    @classmethod
    def default(cls) -> StrategyRegistry:
        return cls(
            {
                "buy_and_hold": BuyAndHoldStrategy,
                "funding_arb_skeleton": FundingArbSkeleton,
                "funding_arb": FundingArbStrategy,
                "factor_portfolio": FactorPortfolioStrategy,
            }
        )

    def names(self) -> list[str]:
        return sorted(self._factories.keys())

    def build(self, name: str, **kwargs: Any) -> Strategy:
        if name not in self._factories:
            raise UnknownStrategy(name)
        return self._factories[name](**kwargs)
