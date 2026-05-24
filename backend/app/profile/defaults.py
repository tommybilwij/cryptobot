"""Single source of truth for profile-scoped keys + safe defaults.

Constraint #1: every numeric / string / dict / bool value a strategy or
service reads must be listed here. Constraint #3: applying a profile walks
this registry; any key absent from the new profile resets to its default
(leak-gap prevention).

Four typed registries:
  * PROFILE_SCOPED_DEFAULTS         — numeric (int/float)
  * PROFILE_SCOPED_STRING_DEFAULTS  — string/enum
  * PROFILE_SCOPED_DICT_DEFAULTS    — nested dict (weights, caps, etc.)
  * PROFILE_SCOPED_BOOL_DEFAULTS    — boolean (kill switches, testnet flags)

Some legacy strategy-level boolean knobs still live in PROFILE_SCOPED_DEFAULTS
as 0.0 / 1.0 floats (mirroring stockbot). New boolean keys belong in the
BOOL registry so `params.get(...)` returns a real `bool`.
"""
from __future__ import annotations

from typing import Any

# ── PROFILE_SCOPED_DEFAULTS ──────────────────────────────────────────────
# Numeric + boolean (stored as 0.0/1.0) profile keys with their safe defaults.

PROFILE_SCOPED_DEFAULTS: dict[str, float] = {
    # ── Strategy A — funding arb ─────────────────────────────────────────
    "strategies.funding_arb.enabled": 1.0,
    "strategies.funding_arb.allocation_pct": 0.40,
    "strategies.funding_arb.entry_bps_per_8h": 8.0,
    "strategies.funding_arb.exit_bps_per_8h": 4.0,
    "strategies.funding_arb.basis_halt_bps": 80.0,
    "strategies.funding_arb.basis_warn_bps": 50.0,
    "strategies.funding_arb.max_position_pct": 0.10,
    "strategies.funding_arb.max_gross_pct": 1.50,
    "strategies.funding_arb.hedge_drift_halt_pct": 0.05,
    "strategies.funding_arb.spot_post_only_ttl_s": 60,
    "strategies.funding_arb.use_predicted_funding": 1.0,
    "strategies.funding_arb.reconcile_interval_s": 15,
    # Phase 6 sizing knobs (read by FundingArbStrategy.evaluate)
    "strategies.funding_arb.max_notional_usdc": 5_000.0,
    "strategies.funding_arb.max_cash_fraction": 0.5,
    "strategies.funding_arb.intervals_per_year": 1095.75,

    # ── Strategy B — factor portfolio ────────────────────────────────────
    "strategies.factor_portfolio.enabled": 1.0,
    "strategies.factor_portfolio.allocation_pct": 0.20,
    "strategies.factor_portfolio.top_decile_pct": 0.10,
    "strategies.factor_portfolio.bottom_decile_pct": 0.10,
    "strategies.factor_portfolio.shorts_enabled": 0.0,
    "strategies.factor_portfolio.lookback_minutes": 1440,
    "strategies.factor_portfolio.cs_alpha": 0.30,
    "strategies.factor_portfolio.scoring.thresholds.strong_buy": 10.0,
    "strategies.factor_portfolio.scoring.thresholds.buy": 7.0,
    "strategies.factor_portfolio.scoring.thresholds.watch": 4.0,
    "strategies.factor_portfolio.scoring.thresholds.llm_gate": 1.0,

    # ── Meta-allocator ──────────────────────────────────────────────────
    "strategies.meta_allocator.enabled": 1.0,
    "strategies.meta_allocator.lookback_days": 30,
    "strategies.meta_allocator.min_weight_pct": 0.10,
    "strategies.meta_allocator.max_weight_pct": 0.70,

    # ── Universe ─────────────────────────────────────────────────────────
    "universe.alt_universe_size": 100,
    "universe.min_daily_volume_usd": 5_000_000,
    "universe.min_listing_age_days": 30,

    # ── Risk (global, applied across all strategies) ─────────────────────
    "risk.max_gross_leverage": 1.50,
    "risk.max_net_leverage": 0.50,
    "risk.max_drawdown_pct": 0.20,
    "risk.daily_drawdown_halt_pct": 0.05,
    "risk.max_gross_per_asset_pct": 0.15,
    "risk.hedge_pair_protection": 1.0,
    "risk.deadman_timeout_s": 60,
    "risk.reconcile_interval_s": 15,
    "risk.position_mismatch_halt": 1.0,
    "risk.kelly.enabled": 0.0,
    "risk.kelly.fraction": 0.25,
    "risk.kelly.baseline_cap": 0.02,
    "risk.vol_target.enabled": 1.0,
    "risk.vol_target.target_pct": 0.015,
    "risk.vol_target.lookback_days": 60,
    "risk.drawdown_brake.enabled": 1.0,
    "risk.drawdown_brake.trigger_pct": 0.05,
    "risk.drawdown_brake.full_pct": 0.15,
    "risk.drawdown_brake.min_mult": 0.25,
    "risk.black_swan_circuit.enabled": 1.0,
    "risk.black_swan_circuit.move_pct": 0.08,
    "risk.black_swan_circuit.window_minutes": 5,

    # ── Execution (global) ───────────────────────────────────────────────
    "execution.max_slippage_bps": 20,
    "execution.taker_fallback_after_s": 60,
    "execution.min_notional_usd": 10,
    "execution.max_retry_attempts": 3,
    "execution.retry_backoff_ms": 500,

    # ── Execution (fees + slippage; used by backtest fill sim + live OMS)
    "execution.slippage_bps.binance": 5.0,
    "execution.slippage_bps.bybit": 5.0,
    "execution.slippage_bps.hyperliquid": 8.0,
    "execution.fee_bps.binance.spot": 10.0,
    "execution.fee_bps.binance.perp": 4.0,
    "execution.fee_bps.bybit.perp": 5.5,
    "execution.fee_bps.hyperliquid.perp": 3.5,

    # ── OMS thresholds + cadence ─────────────────────────────────────────
    "oms.hedge_drift_halt_pct": 0.05,
    "oms.reconcile_drift_halt_pct": 0.02,
    "oms.fill_poll_interval_s": 1.0,
    "oms.max_fill_wait_s": 30.0,
    "oms.audit_snapshot_interval_s": 3600,

    # ── Exchange timeouts ────────────────────────────────────────────────
    "exchanges.binance.timeout_s": 10.0,
    "exchanges.bybit.timeout_s": 10.0,
    "exchanges.hyperliquid.timeout_s": 10.0,

    # ── Backtest assumptions ────────────────────────────────────────────
    "backtest.starting_capital_usd": 10000,
    "backtest.warmup_days": 60,
    "backtest.funding_accrual": 1.0,
    "backtest.survivorship_bias_safe": 1.0,
    "backtest.use_predicted_funding_in_bt": 1.0,
    "backtest.constant_slippage_bps": 3,

    # ── Backtest harness ─────────────────────────────────────────────────
    "backtest.initial_cash_quote_usdc": 10_000.0,
    "backtest.bar_interval_s": 60,
    "backtest.funding_arb_skeleton.hedge_size_fraction": 0.5,
    "metrics.minutes_per_year": 525_600,

    # ── Data health ─────────────────────────────────────────────────────
    "data_health.max_age_s.trades": 60,
    "data_health.max_age_s.klines": 120,
    "data_health.max_age_s.funding": 900,
    "data_health.max_age_s.oi": 900,
    "data_health.max_age_s.on_chain": 86400,
    "data_health.min_health_pct": 0.99,
    "data_health.halt_on_missing": 1.0,
}


# ── PROFILE_SCOPED_STRING_DEFAULTS ───────────────────────────────────────
# String / enum profile keys with their safe defaults.

PROFILE_SCOPED_STRING_DEFAULTS: dict[str, str] = {
    "strategies.funding_arb.perp_execution": "market",
    "strategies.funding_arb.sub_account": "strategy_a_arb",
    # Strategy A — funding arb (Phase 6 strategy-level string defaults).
    "strategies.funding_arb.default_venue": "binance",
    "strategies.funding_arb.default_symbol": "BTCUSDT",
    "strategies.factor_portfolio.rebalance_cron": "0 8 * * *",
    "strategies.factor_portfolio.neutral_holding": "USDC",
    "strategies.factor_portfolio.sub_account": "strategy_b_pf",
    "strategies.meta_allocator.method": "sharpe_weighted",
    "strategies.meta_allocator.rebalance_cron": "0 0 * * SUN",
    "execution.default_order_type": "post_only_limit",
    "execution.client_order_id_prefix": "cb",
    "backtest.fee_model": "per_exchange",
    "backtest.slippage_model": "book_proxy",
    "backtest.rebalance_clock": "exchange_time",
    "backtest.data_source": "parquet",
}


# ── PROFILE_SCOPED_DICT_DEFAULTS ────────────────────────────────────────
# Nested-dict profile keys (e.g. weights, sector caps) with safe defaults.

PROFILE_SCOPED_DICT_DEFAULTS: dict[str, dict[str, Any]] = {
    "universe.core_pairs": {"value": ["BTCUSDT", "ETHUSDT"]},
    "universe.exclusions": {"value": ["USDT", "WBTC", "STETH"]},
    "universe.sector_caps_pct": {
        "DeFi": 0.30,
        "L1": 0.40,
        "L2": 0.30,
        "AI": 0.25,
        "Memes": 0.05,
    },
    "strategies.funding_arb.venues_spot": {"value": ["binance"]},
    "strategies.funding_arb.venues_perp": {"value": ["hyperliquid"]},
    "strategies.funding_arb.funding_period_minutes": {
        "binance": 480,
        "bybit": 480,
        "hyperliquid": 60,
    },
    "strategies.factor_portfolio.scoring.weights": {
        "momentum": 0.18,
        "vol_adj_momentum": 0.12,
        "oi_delta": 0.08,
        "funding_persistence": 0.08,
        "on_chain_flow": 0.10,
        "tokenomics": 0.08,
        "narrative_momentum": 0.10,
        "liquidity_health": 0.06,
        "ml": 0.10,
        "trade_aggressor": 0.04,
        "unlock_pressure": 0.03,
        "social": 0.03,
    },
    "strategies.factor_portfolio.scoring.max_scores": {
        "momentum": 5.0,
        "vol_adj_momentum": 5.0,
        "oi_delta": 3.0,
        "funding_persistence": 3.0,
        "on_chain_flow": 5.0,
        "tokenomics": 4.0,
        "narrative_momentum": 3.0,
        "liquidity_health": 3.0,
        "ml": 5.0,
        "trade_aggressor": 3.0,
        "unlock_pressure": 3.0,
        "social": 3.0,
    },
    "risk.counterparty_caps_pct": {
        "binance": 0.30,
        "bybit": 0.30,
        "hyperliquid": 0.25,
        "cold_storage": 0.30,
    },
    "risk.stable_mix_pct": {"USDT": 0.40, "USDC": 0.40, "AUD": 0.20},
}


# ── PROFILE_SCOPED_BOOL_DEFAULTS ────────────────────────────────────────
# Boolean profile keys with their safe defaults. Kept distinct from the
# numeric registry so `params.get(...)` returns a real `bool` (not 1.0/0.0)
# for kill-switch / testnet flags where the type matters at call sites.

PROFILE_SCOPED_BOOL_DEFAULTS: dict[str, bool] = {
    # ── OMS kill switch ──────────────────────────────────────────────────
    "oms.kill_switch_active": False,
    # ── Per-venue testnet/mainnet toggle ─────────────────────────────────
    "exchanges.binance.use_testnet": True,
    "exchanges.bybit.use_testnet": True,
    "exchanges.hyperliquid.use_testnet": True,
}


def all_profile_keys() -> set[str]:
    """Return every key registered across all four typed registries."""
    return (
        set(PROFILE_SCOPED_DEFAULTS)
        | set(PROFILE_SCOPED_STRING_DEFAULTS)
        | set(PROFILE_SCOPED_DICT_DEFAULTS)
        | set(PROFILE_SCOPED_BOOL_DEFAULTS)
    )
