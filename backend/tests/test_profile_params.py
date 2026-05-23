"""Tests for ProfileParams — the single accessor for profile values."""
from __future__ import annotations

import pytest

from app.profile.params import ProfileParams, UnknownParamPath


def test_get_returns_profile_value_when_present() -> None:
    profile = {
        "strategies": {"funding_arb": {"entry_bps_per_8h": 12.0}}
    }
    params = ProfileParams(profile)
    assert params.get("strategies.funding_arb.entry_bps_per_8h") == 12.0


def test_get_returns_registry_default_when_missing_from_profile() -> None:
    """A path NOT in the profile falls back to its registered default."""
    params = ProfileParams({})
    # default for entry_bps_per_8h is 8.0 per defaults.py
    assert params.get("strategies.funding_arb.entry_bps_per_8h") == 8.0


def test_get_unknown_path_raises() -> None:
    params = ProfileParams({})
    with pytest.raises(UnknownParamPath):
        params.get("strategies.funding_arb.does_not_exist")


def test_get_string_value() -> None:
    profile = {
        "strategies": {"funding_arb": {"sub_account": "custom_sub"}}
    }
    params = ProfileParams(profile)
    assert params.get("strategies.funding_arb.sub_account") == "custom_sub"


def test_get_dict_value() -> None:
    profile: dict = {
        "risk": {"counterparty_caps_pct": {"binance": 0.50, "bybit": 0.20}}
    }
    params = ProfileParams(profile)
    assert params.get("risk.counterparty_caps_pct") == {
        "binance": 0.50,
        "bybit": 0.20,
    }


def test_get_dict_default_used_when_profile_omits_key() -> None:
    params = ProfileParams({})
    caps = params.get("risk.counterparty_caps_pct")
    assert caps["binance"] == 0.30                    # from registry default
