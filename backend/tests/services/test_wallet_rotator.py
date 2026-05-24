"""Tests for WalletRotator — registry-driven sub-account name derivation."""

from __future__ import annotations

from app.profile.params import ProfileParams
from app.services.wallet_rotator import WalletRotator


def test_empty_suffix_returns_base_sub_account() -> None:
    """No active_suffix in registry -> rotation off, base name returned as-is."""
    params = ProfileParams(profile={})
    rotator = WalletRotator(params=params)
    assert rotator.active_sub_account("strategy_a_arb") == "strategy_a_arb"


def test_suffix_a_returns_base_plus_underscore_a() -> None:
    """Setting active_suffix='a' picks the ``_a`` slot."""
    params = ProfileParams(profile={"wallet": {"active_suffix": "a"}})
    rotator = WalletRotator(params=params)
    assert rotator.active_sub_account("strategy_a_arb") == "strategy_a_arb_a"


def test_none_base_propagates_none() -> None:
    """No sub-account configured -> rotation is a no-op."""
    params = ProfileParams(profile={"wallet": {"active_suffix": "a"}})
    rotator = WalletRotator(params=params)
    assert rotator.active_sub_account(None) is None
