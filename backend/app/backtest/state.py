"""Frozen dataclasses describing market state at a single tick.

Strategies see ``MarketState`` and return ``list[Order]``. The engine owns
position bookkeeping; strategies are pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Product = Literal["spot", "perp"]


@dataclass(frozen=True)
class Bar:
    ts_ms: int
    venue: str
    symbol: str
    product: Product
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class MarketSnapshot:
    ts_ms: int
    bars: dict[tuple[str, str, Product], Bar]
    # Per-tick funding rates keyed by (venue, symbol). Empty by default to
    # keep every existing construction site backward-compatible — only the
    # backtest loader and live feed populate this field when funding data
    # is available for the current bar timestamp.
    funding_rates: dict[tuple[str, str], float] = field(default_factory=dict)
    # Per-tick annualised realized volatility keyed by (venue, symbol).
    # Populated by the live runner / backtest loader from a rolling vol
    # estimator (see app.risk.vol_estimator). Strategies fall back to a
    # placeholder when the key is absent (cold start, missing history).
    realized_vols: dict[tuple[str, str], float] = field(default_factory=dict)


@dataclass(frozen=True)
class Position:
    venue: str
    symbol: str
    product: Product
    qty_base: float
    avg_entry_px: float


@dataclass(frozen=True)
class MarketState:
    snapshot: MarketSnapshot
    positions: tuple[Position, ...]
    cash_quote: float
