"""Engine-level E2E: FundingArbStrategy over hand-crafted Parquet with a funding event."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from app.backtest.engine import Engine
from app.backtest.loader import BacktestLoader
from app.market_data.parquet_store import ParquetStore
from app.profile.params import ProfileParams
from app.strategies.funding_arb import FundingArbStrategy


def test_funding_arb_engine_e2e_on_synthetic_data(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
    base = 1704067200000
    # 3 spot bars at the same timestamps
    kline_df = pl.DataFrame(
        {
            "ts_ms": [base, base + 60_000, base + 120_000],
            "open": [60000.0, 60000.0, 60000.0],
            "high": [60000.0, 60000.0, 60000.0],
            "low": [60000.0, 60000.0, 60000.0],
            "close": [60000.0, 60000.0, 60000.0],
            "volume": [10.0, 10.0, 10.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", kline_df, year=2024, month=1)
    # Funding event at tick 2 — 15 bps (above entry 8 bps)
    funding_df = pl.DataFrame(
        {
            "ts_ms": [base + 60_000],
            "predicted": [0.0015],
            "realized": [0.0015],
        }
    )
    store.write_funding("binance", "BTCUSDT", funding_df, year=2024, month=1)

    loader = BacktestLoader(parquet_root=tmp_path)
    strategy = FundingArbStrategy(venue="binance", symbol="BTCUSDT")
    params = ProfileParams(profile={})
    engine = Engine(loader=loader, strategy=strategy, params=params)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 2, tzinfo=UTC)
    # Request both products; ParquetStore doesn't partition by product, so both
    # spot and perp bars resolve to the same kline data (mirrors Phase 6 BacktestService
    # which routes funding_arb with products=['spot', 'perp']).
    result = engine.run(
        venue="binance",
        symbols=["BTCUSDT"],
        products=["spot", "perp"],
        start=start,
        end=end,
    )

    # Tick 2: funding 15 bps > entry 8 bps; strategy emits 2 orders (buy spot + sell perp).
    # Both should fill (spot bar + perp bar both populated from same kline data).
    assert result.num_trades >= 2
