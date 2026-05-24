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


def test_db_pool_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.db_pool_size == 5
    assert s.db_max_overflow == 10
    assert s.db_pool_timeout == 30.0


def test_db_pool_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_POOL_SIZE", "20")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "40")
    s = Settings(_env_file=None)
    assert s.db_pool_size == 20
    assert s.db_max_overflow == 40
