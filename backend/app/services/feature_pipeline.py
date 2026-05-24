"""FeaturePipeline — computes scoring features for Strategy B universe.

Replaces the per-symbol stub feature dict in ``FactorPortfolioStrategy._features``
with a real implementation backed by the Parquet history (DuckDB) and the live
``MarketState`` snapshot.

Features computed:

* ``momentum_30d`` — log-return of close prices over the last 30 days
  (``log(close_last / close_first)``).
* ``realized_vol`` — annualised std-dev of 1m log returns over the same window
  (``stdev × sqrt(525_600)``).
* ``volume_rank`` — symbol's summed 1m volume in the window, normalised to
  ``[0, 1]`` by the universe's max volume.
* ``funding_yield`` — current funding rate from the snapshot, annualised by the
  per-venue ``exchanges.{venue}.funding_intervals_per_year`` cadence.

The pipeline is intentionally tolerant of missing data: a symbol with no
Parquet history yields zeroed features rather than raising, so backtests on
a sparse universe degrade gracefully instead of aborting.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.backtest.state import MarketState
from app.market_data.duckdb_query import DuckDBQuery
from app.profile.params import ProfileParams

_BARS_PER_YEAR_1M = 525_600.0
_MIN_RETURNS = 2
_DEFAULT_MOMENTUM_DAYS = 30
_MS_PER_SECOND = 1000.0


class FeaturePipeline:
    """Compute per-symbol feature dicts for the scoring engine.

    Stateless beyond the Parquet root + params handle. Safe to share across
    ticks; the underlying ``DuckDBQuery`` opens a fresh in-process connection
    per call.
    """

    def __init__(self, *, parquet_root: Path, params: ProfileParams) -> None:
        self._parquet_root = parquet_root
        self._params = params
        self._query = DuckDBQuery(parquet_root=parquet_root)

    def compute_features(
        self,
        *,
        venue: str,
        universe: list[str],
        state: MarketState,
    ) -> dict[str, dict[str, float]]:
        """Return ``{symbol: {feature_name: value}}`` for every symbol in ``universe``.

        Per-symbol features: ``momentum_30d``, ``realized_vol``, ``volume_rank``,
        ``funding_yield``. Missing-data symbols still appear in the output with
        zeroed values — the strategy then scores them at the registry baseline
        rather than excluding them silently.
        """
        if not universe:
            return {}

        ts_ms = state.snapshot.ts_ms
        end = (
            datetime.fromtimestamp(ts_ms / _MS_PER_SECOND, tz=UTC)
            if ts_ms > 0
            else datetime.now(UTC)
        )
        start = end - timedelta(days=_DEFAULT_MOMENTUM_DAYS)

        per_symbol_closes, per_symbol_volume = self._load_history(venue, universe, start, end)

        max_vol = max(per_symbol_volume.values()) if per_symbol_volume else 0.0
        intervals_per_year = float(
            self._params.get(f"exchanges.{venue}.funding_intervals_per_year")
        )

        out: dict[str, dict[str, float]] = {}
        for symbol in universe:
            closes = per_symbol_closes.get(symbol, [])
            features: dict[str, float] = {
                "momentum_30d": self._momentum(closes),
                "realized_vol": self._realized_vol(closes),
                "volume_rank": self._volume_rank(per_symbol_volume.get(symbol, 0.0), max_vol),
                "funding_yield": self._funding_yield(
                    state, venue, symbol, intervals_per_year
                ),
            }
            out[symbol] = features
        return out

    def _load_history(
        self,
        venue: str,
        universe: list[str],
        start: datetime,
        end: datetime,
    ) -> tuple[dict[str, list[float]], dict[str, float]]:
        """Fetch per-symbol close series and summed volume for ``[start, end]``."""
        per_symbol_closes: dict[str, list[float]] = {}
        per_symbol_volume: dict[str, float] = {}
        for symbol in universe:
            try:
                df = self._query.klines(exchange=venue, symbol=symbol, start=start, end=end)
            except Exception:  # noqa: BLE001
                # DuckDB errors on a single symbol must not poison the rest of
                # the universe — degrade to "no history" and continue.
                continue
            if df.height == 0:
                continue
            per_symbol_closes[symbol] = [float(c) for c in df["close"].to_list()]
            per_symbol_volume[symbol] = float(sum(df["volume"].to_list()))
        return per_symbol_closes, per_symbol_volume

    def _momentum(self, closes: list[float]) -> float:
        if len(closes) < _MIN_RETURNS or closes[0] <= 0.0 or closes[-1] <= 0.0:
            return 0.0
        return math.log(closes[-1] / closes[0])

    def _realized_vol(self, closes: list[float]) -> float:
        if len(closes) < _MIN_RETURNS:
            return 0.0
        log_returns: list[float] = []
        for i in range(1, len(closes)):
            prev = closes[i - 1]
            cur = closes[i]
            if prev > 0.0 and cur > 0.0:
                log_returns.append(math.log(cur / prev))
        if len(log_returns) < _MIN_RETURNS:
            return 0.0
        mean = sum(log_returns) / len(log_returns)
        var = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
        return math.sqrt(var) * math.sqrt(_BARS_PER_YEAR_1M)

    def _volume_rank(self, vol: float, max_vol: float) -> float:
        if max_vol <= 0.0:
            return 0.0
        return vol / max_vol

    def _funding_yield(
        self,
        state: MarketState,
        venue: str,
        symbol: str,
        intervals_per_year: float,
    ) -> float:
        funding = state.snapshot.funding_rates.get((venue, symbol))
        if funding is None:
            return 0.0
        return funding * intervals_per_year
