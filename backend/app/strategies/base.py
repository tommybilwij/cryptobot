"""Strategy interface (Protocol). Implementations live in sibling modules.

Per Constraint #1 + #2:
  - `evaluate(state, params)` is a pure function — same code in backtest + live.
  - `required_param_paths()` enumerates registry paths the strategy reads;
    boot fails if any path isn't in the registry.

Implementations MUST NOT contain numeric literals. The AST lint at
`scripts/lint_no_literals_in_strategies.py` enforces this in CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any, Protocol

from app.profile.params import ProfileParams


class ActionType(StrEnum):
    FLAT = "flat"
    LONG_SPOT_SHORT_PERP = "long_spot_short_perp"
    SHORT_SPOT_LONG_PERP = "short_spot_long_perp"
    LONG = "long"
    SHORT = "short"
    HOLD = "hold"
    HALT = "halt"


@dataclass(frozen=True)
class MarketState:
    """Snapshot of relevant market data at a decision moment.

    Per-strategy state shape varies; this is the union surface.
    """

    ts_ms: int
    instrument: str
    spot_price: float | None = None
    perp_price: float | None = None
    predicted_funding_bps_8h: float | None = None
    basis_bps: float | None = None
    open_interest: float | None = None
    features: dict[str, Any] | None = None


@dataclass(frozen=True)
class Action:
    """Decision output. `target_size_pct` is fraction of strategy allocation."""

    type: ActionType
    target_size_pct: float = 0.0
    reason: str = ""


class Strategy(Protocol):
    """Pure-function decision interface."""

    name: str

    @classmethod
    def required_param_paths(cls) -> set[str]:
        """Registry paths this strategy reads. Boot fails if any missing."""
        ...

    def evaluate(self, state: MarketState, params: ProfileParams) -> Action:
        """Return the desired Action given state + profile params."""
        ...

    def warmup_required(self, params: ProfileParams) -> timedelta:
        """Historical data needed before first decision."""
        ...
