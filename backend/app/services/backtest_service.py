"""BacktestService — orchestrates execute(run_id) for the worker job.

Lifecycle: pending → running → (complete | failed).
Writes the equity curve as Parquet at ``<curves_root>/<run_id>.parquet``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.registry import StrategyRegistry
from app.backtest.runner import RunOptions, run_backtest
from app.backtest.state import Product
from app.models.backtest_run import BacktestRun
from app.models.strategy_profile import StrategyProfile
from app.profile.params import ProfileParams


class BacktestService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        parquet_root: Path,
        backtest_curves_root: Path,
        registry: StrategyRegistry | None = None,
    ) -> None:
        self._session = session
        self._parquet_root = parquet_root
        self._curves_root = backtest_curves_root
        self._registry = registry or StrategyRegistry.default()

    async def execute(self, run_id: uuid.UUID) -> None:
        run = await self._load_run(run_id)
        try:
            run.status = "running"
            run.started_at = datetime.now(UTC)
            await self._session.flush()

            profile = await self._load_profile(run.profile_id)
            params = ProfileParams(profile=profile.config)

            # Phase 12: ``funding_arb`` now takes ``symbols: list[str]`` and
            # loops internally; the other strategies remain single-symbol
            # stubs and take the first symbol as their validator.
            if run.strategy_name == "funding_arb":
                strategy = self._registry.build(
                    run.strategy_name,
                    venue=run.venue,
                    symbols=list(run.symbols),
                )
            else:
                symbol = run.symbols[0]
                strategy = self._registry.build(
                    run.strategy_name, venue=run.venue, symbol=symbol
                )
            products: list[Product] = (
                ["spot", "perp"]
                if run.strategy_name in {"funding_arb_skeleton", "funding_arb"}
                else ["spot"]
            )
            opts = RunOptions(
                venue=run.venue,
                symbols=list(run.symbols),
                products=products,
                start=run.start_ts,
                end=run.end_ts,
            )
            result = run_backtest(
                parquet_root=self._parquet_root,
                strategy=strategy,
                params=params,
                options=opts,
            )

            self._curves_root.mkdir(parents=True, exist_ok=True)
            curve_path = self._curves_root / f"{run_id}.parquet"
            result.equity_curve.write_parquet(curve_path, compression="zstd")

            run.status = "complete"
            run.completed_at = datetime.now(UTC)
            run.total_return = result.metrics.total_return
            run.sharpe = result.metrics.sharpe
            run.max_drawdown = result.metrics.max_drawdown
            run.num_trades = result.metrics.num_trades
            run.equity_curve_path = str(curve_path)
            await self._session.flush()
        except Exception as e:
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            run.error_message = f"{type(e).__name__}: {e}"
            await self._session.flush()
            raise

    async def _load_run(self, run_id: uuid.UUID) -> BacktestRun:
        result = await self._session.execute(
            select(BacktestRun).where(BacktestRun.id == run_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise KeyError(f"backtest run {run_id} not found")
        return row

    async def _load_profile(self, profile_id: uuid.UUID) -> StrategyProfile:
        result = await self._session.execute(
            select(StrategyProfile).where(StrategyProfile.id == profile_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise KeyError(f"profile {profile_id} not found")
        return profile
