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
