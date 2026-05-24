"""OMS exception hierarchy — halt-class errors that suspend trading."""

from __future__ import annotations


class OMSError(RuntimeError):
    """Base class for all OMS errors."""


class KillSwitchActive(OMSError):
    """Kill switch flag is set in the active profile; refuse to dispatch."""


class HedgeDriftHalt(OMSError):
    """Spot/perp position mismatch exceeded threshold."""


class ReconciliationDriftHalt(OMSError):
    """Book vs exchange position mismatch exceeded threshold."""


class UnconfiguredVenueError(OMSError):
    """Strategy emitted an order for a venue with no configured adapter."""
