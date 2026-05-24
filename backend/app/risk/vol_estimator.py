"""Rolling realized-volatility estimator (HP1).

Annualised stdev of log returns over a rolling window of bar closes. Used to
replace the prior hardcoded ``_PHASE_10_VOL_PLACEHOLDER`` passed to
``SizingService`` when Kelly sizing is enabled — once the runner has seeded
enough closes, the strategy reads the live estimate from
``MarketSnapshot.realized_vols`` instead of the placeholder.

The estimator is deliberately stateful + in-memory: one deque per
``(venue, symbol)`` keyed instance, sized by the configured window. The live
runner records each tick's close; the backtest loader can bulk-seed via
``seed_from_bars`` before stepping. The estimator itself is unit-of-measure
only — every tunable (window, bars-per-year) flows in via constructor /
method argument so the no-literals lint stays clean at strategy call sites.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Iterable

# 1-minute bars over 365 days: 24 * 60 * 365.
_BARS_PER_YEAR_1M = 525_600.0
# Need at least two returns (so three closes) to compute a sample variance.
_MIN_RETURNS_FOR_VOL = 2


class RollingVolEstimator:
    """Annualised stdev of log returns over a fixed-length rolling window.

    The estimator stores the last ``window_bars`` close prices per
    ``(venue, symbol)``. ``annualised_vol`` returns ``sqrt(variance) *
    sqrt(bars_per_year)``. Returns 0.0 when the buffer is too small or all
    closes are constant — callers fall back to a placeholder in that case.
    """

    def __init__(self, *, window_bars: int = 30) -> None:
        self._window = window_bars
        self._closes: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=window_bars)
        )

    def record(self, *, venue: str, symbol: str, close_px: float) -> None:
        """Append one close price to the rolling window for ``(venue, symbol)``."""
        self._closes[(venue, symbol)].append(close_px)

    def annualised_vol(
        self, *, venue: str, symbol: str, bars_per_year: float = _BARS_PER_YEAR_1M
    ) -> float:
        """Return the annualised stdev of log returns; 0.0 if undefined."""
        closes = list(self._closes.get((venue, symbol), []))
        if len(closes) < _MIN_RETURNS_FOR_VOL:
            return 0.0
        log_returns: list[float] = []
        for i in range(1, len(closes)):
            prev = closes[i - 1]
            cur = closes[i]
            if prev > 0.0 and cur > 0.0:
                log_returns.append(math.log(cur / prev))
        if len(log_returns) < _MIN_RETURNS_FOR_VOL:
            return 0.0
        mean = sum(log_returns) / len(log_returns)
        var = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
        return math.sqrt(var) * math.sqrt(bars_per_year)

    def seed_from_bars(self, venue: str, symbol: str, closes: Iterable[float]) -> None:
        """Test helper: bulk-seed close prices for ``(venue, symbol)``."""
        for px in closes:
            self.record(venue=venue, symbol=symbol, close_px=px)
