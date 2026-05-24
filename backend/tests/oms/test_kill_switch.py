"""Tests for KillSwitch."""

from __future__ import annotations

from app.oms.kill_switch import KillSwitch
from app.profile.params import ProfileParams


def test_default_is_inactive() -> None:
    ks = KillSwitch(params=ProfileParams(profile={}))
    assert ks.is_active() is False


def test_profile_flag_activates_kill_switch() -> None:
    ks = KillSwitch(params=ProfileParams(profile={"oms": {"kill_switch_active": True}}))
    assert ks.is_active() is True
