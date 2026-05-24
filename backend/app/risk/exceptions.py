"""Risk-class exception hierarchy."""

from __future__ import annotations


class RiskError(RuntimeError):
    """Base for halt-class risk errors."""


class DrawdownBrakeHalt(RiskError):
    """Equity dropped > trigger_pct from peak; halt trading."""
