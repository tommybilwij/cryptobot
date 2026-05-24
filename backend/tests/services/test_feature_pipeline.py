"""Tests for FeaturePipeline."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from app.backtest.state import MarketSnapshot, MarketState
from app.market_data.parquet_store import ParquetStore
from app.profile.params import ProfileParams
from app.services.feature_pipeline import FeaturePipeline

# 2024-01-01 00:00:00 UTC — anchor for synthetic 1m klines.
_BASE_TS_MS = 1_704_067_200_000
_MINUTE_MS = 60_000


def _write_klines(root: Path, symbol: str, closes: list[float]) -> None:
    store = ParquetStore(root=root)
    n = len(closes)
    df = pl.DataFrame(
        {
            "ts_ms": [_BASE_TS_MS + i * _MINUTE_MS for i in range(n)],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [10.0] * n,
        }
    )
    store.write_klines("binance", symbol, df, year=2024, month=1)


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def _state(
    ts_ms: int = 0, funding_rates: dict[tuple[str, str], float] | None = None
) -> MarketState:
    return MarketState(
        snapshot=MarketSnapshot(ts_ms=ts_ms, bars={}, funding_rates=funding_rates or {}),
        positions=(),
        cash_quote=10_000.0,
    )


def test_empty_universe_returns_empty(tmp_path: Path) -> None:
    """Empty universe -> empty dict (no DuckDB calls)."""
    p = FeaturePipeline(parquet_root=tmp_path, params=_params())
    assert p.compute_features(venue="binance", universe=[], state=_state()) == {}


def test_missing_data_yields_zero_features(tmp_path: Path) -> None:
    """Symbol with no Parquet history -> all-zero feature dict, no exception."""
    p = FeaturePipeline(parquet_root=tmp_path, params=_params())
    result = p.compute_features(venue="binance", universe=["BTCUSDT"], state=_state())
    assert result["BTCUSDT"]["momentum_30d"] == 0.0
    assert result["BTCUSDT"]["realized_vol"] == 0.0
    assert result["BTCUSDT"]["volume_rank"] == 0.0
    assert result["BTCUSDT"]["funding_yield"] == 0.0


def test_positive_momentum_from_rising_closes(tmp_path: Path) -> None:
    """Monotonically rising closes -> positive 30d log-return."""
    _write_klines(tmp_path, "BTCUSDT", [60000.0, 60500.0, 61000.0, 61500.0, 62000.0])
    p = FeaturePipeline(parquet_root=tmp_path, params=_params())
    result = p.compute_features(
        venue="binance",
        universe=["BTCUSDT"],
        state=_state(ts_ms=_BASE_TS_MS + 5 * _MINUTE_MS),
    )
    assert result["BTCUSDT"]["momentum_30d"] > 0.0


def test_funding_yield_annualised(tmp_path: Path) -> None:
    """1 bps per 8h × 1095.75 intervals/year ≈ 0.109575 annualised."""
    p = FeaturePipeline(parquet_root=tmp_path, params=_params())
    result = p.compute_features(
        venue="binance",
        universe=["BTCUSDT"],
        state=_state(funding_rates={("binance", "BTCUSDT"): 0.0001}),
    )
    assert result["BTCUSDT"]["funding_yield"] == pytest.approx(0.109575, rel=1e-3)
