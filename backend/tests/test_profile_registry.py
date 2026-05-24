"""Tests for profile registry self-consistency."""
from __future__ import annotations

import ast
import pathlib

from app.profile.defaults import (
    PROFILE_SCOPED_BOOL_DEFAULTS,
    PROFILE_SCOPED_DEFAULTS,
    PROFILE_SCOPED_DICT_DEFAULTS,
    PROFILE_SCOPED_STRING_DEFAULTS,
    all_profile_keys,
)

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
STRATEGIES_DIR = REPO_ROOT / "backend" / "app" / "strategies"


def test_no_key_appears_in_more_than_one_registry() -> None:
    """A path cannot be registered as both numeric and string, etc."""
    numeric = set(PROFILE_SCOPED_DEFAULTS)
    string = set(PROFILE_SCOPED_STRING_DEFAULTS)
    dictv = set(PROFILE_SCOPED_DICT_DEFAULTS)
    boolv = set(PROFILE_SCOPED_BOOL_DEFAULTS)
    assert numeric & string == set(), "key in both numeric + string registries"
    assert numeric & dictv == set(), "key in both numeric + dict registries"
    assert numeric & boolv == set(), "key in both numeric + bool registries"
    assert string & dictv == set(), "key in both string + dict registries"
    assert string & boolv == set(), "key in both string + bool registries"
    assert dictv & boolv == set(), "key in both dict + bool registries"


def test_all_profile_keys_is_union() -> None:
    """all_profile_keys() returns the union of the four registries."""
    expected = (
        set(PROFILE_SCOPED_DEFAULTS)
        | set(PROFILE_SCOPED_STRING_DEFAULTS)
        | set(PROFILE_SCOPED_DICT_DEFAULTS)
        | set(PROFILE_SCOPED_BOOL_DEFAULTS)
    )
    assert all_profile_keys() == expected


def test_numeric_defaults_are_numeric() -> None:
    """PROFILE_SCOPED_DEFAULTS values must be int or float."""
    for key, value in PROFILE_SCOPED_DEFAULTS.items():
        assert isinstance(value, (int, float)), (
            f"non-numeric default for {key}: {value!r}"
        )


def test_string_defaults_are_strings() -> None:
    """PROFILE_SCOPED_STRING_DEFAULTS values must be str."""
    for key, value in PROFILE_SCOPED_STRING_DEFAULTS.items():
        assert isinstance(value, str), f"non-string default for {key}: {value!r}"


def test_dict_defaults_are_dicts() -> None:
    """PROFILE_SCOPED_DICT_DEFAULTS values must be dict."""
    for key, value in PROFILE_SCOPED_DICT_DEFAULTS.items():
        assert isinstance(value, dict), f"non-dict default for {key}: {value!r}"


def test_dotted_paths_are_valid_identifiers() -> None:
    """Every dotted path segment must be a valid identifier — no spaces / hyphens."""
    for key in all_profile_keys():
        for segment in key.split("."):
            assert segment.isidentifier(), (
                f"non-identifier segment {segment!r} in path {key!r}"
            )


def _collect_params_get_paths(py_file: pathlib.Path) -> list[str]:
    """Return every string passed to a `.get(...)` method call in py_file."""
    tree = ast.parse(py_file.read_text())
    paths: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            paths.append(node.args[0].value)
    return paths


def test_every_params_get_path_is_in_registry() -> None:
    """If a strategy calls `params.get('foo.bar')`, 'foo.bar' must be registered."""
    registered = all_profile_keys()
    for py_file in STRATEGIES_DIR.rglob("*.py"):
        if py_file.name == "base.py":
            continue
        for path in _collect_params_get_paths(py_file):
            assert path in registered, (
                f"{py_file}: params.get({path!r}) but path not in registry"
            )


def test_execution_slippage_keys_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    for venue in ("binance", "bybit", "hyperliquid"):
        key = f"execution.slippage_bps.{venue}"
        assert key in PROFILE_SCOPED_DEFAULTS, f"missing {key}"
        assert isinstance(PROFILE_SCOPED_DEFAULTS[key], float)


def test_execution_fee_keys_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    expected = [
        "execution.fee_bps.binance.spot",
        "execution.fee_bps.binance.perp",
        "execution.fee_bps.bybit.perp",
        "execution.fee_bps.hyperliquid.perp",
    ]
    for key in expected:
        assert key in PROFILE_SCOPED_DEFAULTS, f"missing {key}"
        assert isinstance(PROFILE_SCOPED_DEFAULTS[key], float)


def test_backtest_keys_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    assert PROFILE_SCOPED_DEFAULTS["backtest.initial_cash_quote_usdc"] == 10_000.0
    assert PROFILE_SCOPED_DEFAULTS["backtest.bar_interval_s"] == 60
    assert PROFILE_SCOPED_DEFAULTS["metrics.minutes_per_year"] == 525_600


def test_funding_arb_skeleton_fraction_key_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS
    assert PROFILE_SCOPED_DEFAULTS["backtest.funding_arb_skeleton.hedge_size_fraction"] == 0.5


def test_bool_defaults_registry_exists() -> None:
    from app.profile.defaults import PROFILE_SCOPED_BOOL_DEFAULTS

    assert isinstance(PROFILE_SCOPED_BOOL_DEFAULTS, dict)


def test_oms_kill_switch_default_false() -> None:
    from app.profile.defaults import PROFILE_SCOPED_BOOL_DEFAULTS

    assert PROFILE_SCOPED_BOOL_DEFAULTS["oms.kill_switch_active"] is False


def test_oms_drift_thresholds_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    assert PROFILE_SCOPED_DEFAULTS["oms.hedge_drift_halt_pct"] == 0.05
    assert PROFILE_SCOPED_DEFAULTS["oms.reconcile_drift_halt_pct"] == 0.02
    assert PROFILE_SCOPED_DEFAULTS["oms.fill_poll_interval_s"] == 1.0
    assert PROFILE_SCOPED_DEFAULTS["oms.max_fill_wait_s"] == 30.0
    assert PROFILE_SCOPED_DEFAULTS["oms.audit_snapshot_interval_s"] == 3600


def test_exchange_testnet_defaults_true() -> None:
    from app.profile.defaults import PROFILE_SCOPED_BOOL_DEFAULTS

    for venue in ("binance", "bybit", "hyperliquid"):
        assert PROFILE_SCOPED_BOOL_DEFAULTS[f"exchanges.{venue}.use_testnet"] is True


def test_exchange_timeout_defaults_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    for venue in ("binance", "bybit", "hyperliquid"):
        assert PROFILE_SCOPED_DEFAULTS[f"exchanges.{venue}.timeout_s"] == 10.0


def test_profile_params_resolves_bool_default() -> None:
    from app.profile.params import ProfileParams

    p = ProfileParams(profile={})
    assert p.get("oms.kill_switch_active") is False


def test_profile_params_bool_override() -> None:
    from app.profile.params import ProfileParams

    p = ProfileParams(profile={"oms": {"kill_switch_active": True}})
    assert p.get("oms.kill_switch_active") is True


def test_funding_arb_thresholds_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    # Phase 1+2 seeded entry=8 / exit=4 bps thresholds; Phase 6 strategy reads these
    assert PROFILE_SCOPED_DEFAULTS["strategies.funding_arb.entry_bps_per_8h"] == 8.0
    assert PROFILE_SCOPED_DEFAULTS["strategies.funding_arb.exit_bps_per_8h"] == 4.0
    assert PROFILE_SCOPED_DEFAULTS["strategies.funding_arb.max_notional_usdc"] == 5_000.0
    assert PROFILE_SCOPED_DEFAULTS["strategies.funding_arb.max_cash_fraction"] == 0.5
    assert PROFILE_SCOPED_DEFAULTS["strategies.funding_arb.intervals_per_year"] == 1095.75


def test_funding_arb_string_defaults_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_STRING_DEFAULTS

    assert PROFILE_SCOPED_STRING_DEFAULTS["strategies.funding_arb.default_venue"] == "binance"
    assert PROFILE_SCOPED_STRING_DEFAULTS["strategies.funding_arb.default_symbol"] == "BTCUSDT"


def test_exchange_url_defaults_present() -> None:
    from app.profile.defaults import PROFILE_SCOPED_STRING_DEFAULTS
    expected = [
        "exchanges.binance.spot_base_url_testnet",
        "exchanges.binance.perp_base_url_testnet",
        "exchanges.binance.spot_base_url_mainnet",
        "exchanges.bybit.base_url_testnet",
        "exchanges.bybit.base_url_mainnet",
        "exchanges.hyperliquid.base_url_testnet",
        "exchanges.hyperliquid.base_url_mainnet",
    ]
    for key in expected:
        assert key in PROFILE_SCOPED_STRING_DEFAULTS, f"missing {key}"


def test_live_tick_interval_default() -> None:
    """Phase 8: live.tick_interval_s = 60.0 (float)."""
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    assert PROFILE_SCOPED_DEFAULTS["live.tick_interval_s"] == 60.0
    assert isinstance(PROFILE_SCOPED_DEFAULTS["live.tick_interval_s"], float)


def test_live_snapshot_interval_default() -> None:
    """Phase 8: live.snapshot_interval_s = 3600.0 (hourly heartbeat)."""
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    assert PROFILE_SCOPED_DEFAULTS["live.snapshot_interval_s"] == 3600.0
    assert isinstance(PROFILE_SCOPED_DEFAULTS["live.snapshot_interval_s"], float)


def test_live_cold_start_grace_default() -> None:
    """Phase 8: live.cold_start_grace_s = 300.0 (5-minute warm-up)."""
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    assert PROFILE_SCOPED_DEFAULTS["live.cold_start_grace_s"] == 300.0
    assert isinstance(PROFILE_SCOPED_DEFAULTS["live.cold_start_grace_s"], float)


def test_drawdown_brake_peak_equity_default() -> None:
    """Phase 8 brake seeds initial peak from profile; 0.0 → cold start."""
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    assert PROFILE_SCOPED_DEFAULTS["risk.drawdown_brake.peak_equity"] == 0.0
    assert isinstance(PROFILE_SCOPED_DEFAULTS["risk.drawdown_brake.peak_equity"], float)


def test_live_enabled_default_false() -> None:
    """Default-safe: live.enabled = False (master gate off)."""
    from app.profile.defaults import PROFILE_SCOPED_BOOL_DEFAULTS

    assert PROFILE_SCOPED_BOOL_DEFAULTS["live.enabled"] is False


def test_live_dry_run_mode_default_true() -> None:
    """Default-safe: live.dry_run_mode = True (paper exchange in-memory)."""
    from app.profile.defaults import PROFILE_SCOPED_BOOL_DEFAULTS

    assert PROFILE_SCOPED_BOOL_DEFAULTS["live.dry_run_mode"] is True


def test_live_venue_string_default() -> None:
    """Phase 8: live.venue = 'binance'."""
    from app.profile.defaults import PROFILE_SCOPED_STRING_DEFAULTS

    assert PROFILE_SCOPED_STRING_DEFAULTS["live.venue"] == "binance"
    assert isinstance(PROFILE_SCOPED_STRING_DEFAULTS["live.venue"], str)


def test_alerts_timeout_s_default() -> None:
    """Phase 9: alerts.timeout_s = 5.0 (float)."""
    from app.profile.defaults import PROFILE_SCOPED_DEFAULTS

    assert PROFILE_SCOPED_DEFAULTS["alerts.timeout_s"] == 5.0
    assert isinstance(PROFILE_SCOPED_DEFAULTS["alerts.timeout_s"], float)


def test_alerts_webhook_url_default_empty() -> None:
    """Phase 9: alerts.webhook_url defaults to '' (no-op alerter)."""
    from app.profile.defaults import PROFILE_SCOPED_STRING_DEFAULTS

    assert PROFILE_SCOPED_STRING_DEFAULTS["alerts.webhook_url"] == ""
    assert isinstance(PROFILE_SCOPED_STRING_DEFAULTS["alerts.webhook_url"], str)


def test_alerts_heartbeat_severity_default() -> None:
    """Phase 9: alerts.heartbeat_severity = 'info'."""
    from app.profile.defaults import PROFILE_SCOPED_STRING_DEFAULTS

    assert PROFILE_SCOPED_STRING_DEFAULTS["alerts.heartbeat_severity"] == "info"
    assert isinstance(PROFILE_SCOPED_STRING_DEFAULTS["alerts.heartbeat_severity"], str)


def test_alerts_send_heartbeats_default_false() -> None:
    """Phase 9: default-safe alerts.send_heartbeats = False (no chatty webhook)."""
    from app.profile.defaults import PROFILE_SCOPED_BOOL_DEFAULTS

    assert PROFILE_SCOPED_BOOL_DEFAULTS["alerts.send_heartbeats"] is False
