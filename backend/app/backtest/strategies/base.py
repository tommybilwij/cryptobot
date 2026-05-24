"""Strategy Protocol for the backtest engine. Same shape will be reused live."""

from __future__ import annotations

from typing import Protocol

from app.backtest.orders import Order
from app.backtest.state import MarketState
from app.profile.params import ProfileParams


class Strategy(Protocol):
    name: str

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]: ...
