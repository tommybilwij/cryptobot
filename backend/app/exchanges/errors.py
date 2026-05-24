"""ExchangeError hierarchy — uniform error mapping across venues."""

from __future__ import annotations


class ExchangeError(RuntimeError):
    """Base class for all exchange-side errors."""


class RateLimited(ExchangeError):
    """HTTP 429 or venue-specific rate-limit response."""


class Rejected(ExchangeError):
    """Order rejected (validation, insufficient margin, etc.). HTTP 4xx."""


class Timeout(ExchangeError):
    """No response within timeout window."""


class AuthFailed(ExchangeError):
    """HTTP 401/403 — bad keys or signature mismatch. CRITICAL: halt trading."""


class UnconfiguredVenue(ExchangeError):
    """Profile asked for a venue that isn't configured."""
