"""Tests for Pydantic schemas validating profile JSONB."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.strategy_profile import StrategyProfileConfig


def test_minimal_valid_profile_parses() -> None:
    config = {
        "meta": {"name": "balanced_v1", "version": 1},
    }
    parsed = StrategyProfileConfig.model_validate(config)
    assert parsed.meta.name == "balanced_v1"


def test_full_profile_parses() -> None:
    config = {
        "meta": {"name": "balanced_v1", "version": 1},
        "universe": {
            "core_pairs": ["BTCUSDT", "ETHUSDT"],
            "alt_universe_size": 100,
        },
        "strategies": {
            "funding_arb": {
                "enabled": True,
                "allocation_pct": 0.40,
                "entry_bps_per_8h": 8.0,
            },
            "factor_portfolio": {
                "enabled": True,
                "allocation_pct": 0.20,
            },
        },
        "risk": {
            "max_gross_leverage": 1.50,
        },
    }
    parsed = StrategyProfileConfig.model_validate(config)
    assert parsed.strategies.funding_arb.entry_bps_per_8h == 8.0


def test_allocation_pct_out_of_range_rejects() -> None:
    config = {
        "meta": {"name": "x", "version": 1},
        "strategies": {"funding_arb": {"allocation_pct": 1.5}},  # > 1.0
    }
    with pytest.raises(ValidationError):
        StrategyProfileConfig.model_validate(config)


def test_negative_leverage_rejects() -> None:
    config = {
        "meta": {"name": "x", "version": 1},
        "risk": {"max_gross_leverage": -1.0},
    }
    with pytest.raises(ValidationError):
        StrategyProfileConfig.model_validate(config)
