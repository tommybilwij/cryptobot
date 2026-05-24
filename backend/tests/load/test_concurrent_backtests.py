"""Load test: N concurrent BacktestService.execute calls (slow marker).

Smoke-level concurrency sanity check — N runs in a row that all reach the
``complete`` status. Tagged ``slow`` so the default ``pytest`` run skips it;
use ``just load-test`` to drive it explicitly.

The async session fixture is single-connection so the runs go sequentially
inside the test; the goal is to flush out resource-exhaustion bugs (file
handles, parquet readers, curve writers) at higher fan-out, not to test
true parallel scheduling.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.parquet_store import ParquetStore
from app.models.backtest_run import BacktestRun
from app.models.strategy_profile import StrategyProfile
from app.services.backtest_service import BacktestService

_CONCURRENT_RUNS = 5


def _hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


def _write_klines(root: Path) -> None:
    store = ParquetStore(root=root)
    base = 1704067200000
    df = pl.DataFrame(
        {
            "ts_ms": [base + i * 60_000 for i in range(10)],
            "open": [60000.0] * 10,
            "high": [60000.0] * 10,
            "low": [60000.0] * 10,
            "close": [60000.0] * 10,
            "volume": [10.0] * 10,
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=2024, month=1)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_n_concurrent_backtests(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """Sanity check: N backtest jobs complete without deadlock or resource leak."""
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _write_klines(parquet_root)
    curves_root = tmp_path / "curves"

    profile = StrategyProfile(name="load", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    run_ids = []
    for _ in range(_CONCURRENT_RUNS):
        run = BacktestRun(
            profile_id=profile.id,
            profile_version=1,
            profile_hash=_hash({}),
            strategy_name="buy_and_hold",
            venue="binance",
            symbols=["BTCUSDT"],
            start_ts=datetime(2024, 1, 1, tzinfo=UTC),
            end_ts=datetime(2024, 1, 1, 0, 10, tzinfo=UTC),
            status="pending",
        )
        db_session.add(run)
        await db_session.flush()
        run_ids.append(run.id)
    await db_session.commit()

    service = BacktestService(
        session=db_session,
        parquet_root=parquet_root,
        backtest_curves_root=curves_root,
    )

    # Sequential drive — AsyncSession is not concurrent-safe. The point of
    # the harness is detecting accumulated state / handle leaks across N
    # runs, not parallel scheduler stress (that belongs in a worker test).
    for rid in run_ids:
        await service.execute(rid)

    for rid in run_ids:
        r = (
            await db_session.execute(
                select(BacktestRun).where(BacktestRun.id == rid)
            )
        ).scalar_one()
        assert r.status == "complete"
