"""run_backtest — high-level glue from inputs to BacktestRunResult."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

from app.backtest.engine import Engine
from app.backtest.loader import BacktestLoader
from app.backtest.metrics import BacktestMetrics, compute_metrics
from app.backtest.state import Product
from app.backtest.strategies.base import Strategy
from app.profile.params import ProfileParams


@dataclass(frozen=True)
class RunOptions:
    venue: str
    symbols: list[str]
    products: list[Product]
    start: datetime
    end: datetime


@dataclass
class BacktestRunResult:
    equity_curve: pl.DataFrame
    metrics: BacktestMetrics


def run_backtest(
    *,
    parquet_root: Path,
    strategy: Strategy,
    params: ProfileParams,
    options: RunOptions,
) -> BacktestRunResult:
    loader = BacktestLoader(parquet_root=parquet_root)
    engine = Engine(loader=loader, strategy=strategy, params=params)
    engine_result = engine.run(
        venue=options.venue,
        symbols=options.symbols,
        products=options.products,
        start=options.start,
        end=options.end,
    )
    metrics = compute_metrics(
        engine_result.equity_curve, params=params, num_trades=engine_result.num_trades
    )
    return BacktestRunResult(
        equity_curve=engine_result.equity_curve, metrics=metrics
    )
