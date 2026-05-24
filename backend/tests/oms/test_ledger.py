"""Tests for MultiVenueCashLedger."""

from __future__ import annotations

from app.oms.ledger import MultiVenueCashLedger


def test_initial_balance_zero() -> None:
    ledger = MultiVenueCashLedger()
    assert ledger.total() == 0.0


def test_set_venue_balance() -> None:
    ledger = MultiVenueCashLedger()
    ledger.set_venue_balance("binance", 5000.0)
    ledger.set_venue_balance("hyperliquid", 3000.0)
    assert ledger.total() == 8000.0
    assert ledger.get_venue_balance("binance") == 5000.0


def test_debit_credit() -> None:
    ledger = MultiVenueCashLedger()
    ledger.set_venue_balance("binance", 5000.0)
    ledger.debit("binance", 1000.0)
    assert ledger.get_venue_balance("binance") == 4000.0
    ledger.credit("binance", 500.0)
    assert ledger.get_venue_balance("binance") == 4500.0


def test_get_unknown_venue_returns_zero() -> None:
    ledger = MultiVenueCashLedger()
    assert ledger.get_venue_balance("unknown") == 0.0
