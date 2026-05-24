"""Tests for Settings exchange-key fields."""

from __future__ import annotations

import pytest

from app.config import Settings


def test_binance_keys_default_empty() -> None:
    s = Settings(_env_file=None)
    assert s.binance_api_key == ""
    assert s.binance_api_secret == ""


def test_bybit_keys_default_empty() -> None:
    s = Settings(_env_file=None)
    assert s.bybit_api_key == ""
    assert s.bybit_api_secret == ""


def test_hyperliquid_key_default_empty() -> None:
    s = Settings(_env_file=None)
    assert s.hyperliquid_wallet_private_key == ""


def test_keys_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "test-secret")
    s = Settings(_env_file=None)
    assert s.binance_api_key == "test-key"
    assert s.binance_api_secret == "test-secret"
