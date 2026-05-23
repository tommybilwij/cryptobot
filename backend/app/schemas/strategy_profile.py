"""Pydantic v2 schemas validating strategy profile JSONB.

Schemas mirror the registry structure but enforce ranges. Schema validation is
the *boundary check* — internal code reads via ProfileParams which trusts the
profile is already validated.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProfileMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1)
    description: str | None = None


class FundingArbConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    allocation_pct: float = Field(ge=0.0, le=1.0, default=0.40)
    entry_bps_per_8h: float = Field(ge=-100.0, le=100.0, default=8.0)
    exit_bps_per_8h: float = Field(ge=-100.0, le=100.0, default=4.0)
    basis_halt_bps: float = Field(ge=0.0, le=10_000.0, default=80.0)
    max_position_pct: float = Field(ge=0.0, le=1.0, default=0.10)
    hedge_drift_halt_pct: float = Field(ge=0.0, le=1.0, default=0.05)
    venues_spot: list[str] = Field(default_factory=lambda: ["binance"])
    venues_perp: list[str] = Field(default_factory=lambda: ["hyperliquid"])
    sub_account: str = "strategy_a_arb"


class FactorPortfolioConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    allocation_pct: float = Field(ge=0.0, le=1.0, default=0.20)
    top_decile_pct: float = Field(ge=0.0, le=0.50, default=0.10)
    bottom_decile_pct: float = Field(ge=0.0, le=0.50, default=0.10)
    shorts_enabled: bool = False
    rebalance_cron: str = "0 8 * * *"
    sub_account: str = "strategy_b_pf"


class MetaAllocatorConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    method: str = Field(
        default="sharpe_weighted",
        pattern="^(sharpe_weighted|risk_parity|static|kelly)$",
    )
    lookback_days: int = Field(ge=1, le=365, default=30)
    min_weight_pct: float = Field(ge=0.0, le=1.0, default=0.10)
    max_weight_pct: float = Field(ge=0.0, le=1.0, default=0.70)
    rebalance_cron: str = "0 0 * * SUN"


class StrategiesConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    funding_arb: FundingArbConfig = Field(default_factory=FundingArbConfig)
    factor_portfolio: FactorPortfolioConfig = Field(default_factory=FactorPortfolioConfig)
    meta_allocator: MetaAllocatorConfig = Field(default_factory=MetaAllocatorConfig)


class UniverseConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    core_pairs: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    alt_universe_size: int = Field(ge=1, le=1000, default=100)
    min_daily_volume_usd: float = Field(ge=0.0, default=5_000_000.0)
    min_listing_age_days: int = Field(ge=0, le=365, default=30)


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    max_gross_leverage: float = Field(ge=0.0, le=10.0, default=1.50)
    max_net_leverage: float = Field(ge=0.0, le=10.0, default=0.50)
    max_drawdown_pct: float = Field(ge=0.0, le=1.0, default=0.20)
    daily_drawdown_halt_pct: float = Field(ge=0.0, le=1.0, default=0.05)
    max_gross_per_asset_pct: float = Field(ge=0.0, le=1.0, default=0.15)
    deadman_timeout_s: int = Field(ge=1, le=3600, default=60)


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    default_order_type: str = Field(
        default="post_only_limit",
        pattern="^(post_only_limit|limit|market|ioc)$",
    )
    max_slippage_bps: int = Field(ge=0, le=10_000, default=20)
    taker_fallback_after_s: int = Field(ge=0, le=3600, default=60)
    min_notional_usd: float = Field(ge=0.0, default=10.0)


class BacktestConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    starting_capital_usd: float = Field(ge=0.0, default=10_000.0)
    fee_model: str = Field(default="per_exchange", pattern="^(per_exchange|constant_bps)$")
    slippage_model: str = Field(
        default="book_proxy", pattern="^(book_proxy|atr_based|constant_bps)$"
    )
    funding_accrual: bool = True
    survivorship_bias_safe: bool = True
    start_date: str | None = None
    end_date: str | None = None


class StrategyProfileConfig(BaseModel):
    """Root schema for the profile JSONB blob."""

    model_config = ConfigDict(extra="allow")
    meta: ProfileMeta
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    strategies: StrategiesConfig = Field(default_factory=StrategiesConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
