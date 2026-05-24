"""Tests for BacktestService — persists run lifecycle + writes equity curve Parquet."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.parquet_store import ParquetStore
from app.models.backtest_run import BacktestRun
from app.models.strategy_profile import StrategyProfile
from app.services.backtest_service import BacktestService


def _canonical_json(d: dict) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


def _profile_hash(config: dict) -> str:
    return hashlib.sha256(_canonical_json(config).encode()).hexdigest()


def _write_klines(root: Path) -> None:
    store = ParquetStore(root=root)
    base = 1704067200000
    df = pl.DataFrame(
        {
            "ts_ms": [base, base + 60_000, base + 120_000],
            "open": [60000.0, 60100.0, 60200.0],
            "high": [60050.0, 60150.0, 60250.0],
            "low": [59950.0, 60050.0, 60150.0],
            "close": [60000.0, 60100.0, 60200.0],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=2024, month=1)


@pytest.mark.asyncio
async def test_run_persists_and_writes_curve(db_session: AsyncSession, tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _write_klines(parquet_root)
    curves_root = tmp_path / "backtest_runs"

    profile = StrategyProfile(
        name="test-profile",
        version=1,
        is_active=False,
        config={},
    )
    db_session.add(profile)
    await db_session.flush()

    run = BacktestRun(
        profile_id=profile.id,
        profile_version=profile.version,
        profile_hash=_profile_hash(profile.config),
        strategy_name="buy_and_hold",
        venue="binance",
        symbols=["BTCUSDT"],
        start_ts=datetime(2024, 1, 1, tzinfo=UTC),
        end_ts=datetime(2024, 1, 1, 0, 2, tzinfo=UTC),
        status="pending",
    )
    db_session.add(run)
    await db_session.flush()
    run_id = run.id

    service = BacktestService(
        session=db_session,
        parquet_root=parquet_root,
        backtest_curves_root=curves_root,
    )
    await service.execute(run_id)

    await db_session.refresh(run)
    assert run.status == "complete"
    assert run.num_trades is not None
    assert run.equity_curve_path is not None
    assert (curves_root / f"{run_id}.parquet").exists()


@pytest.mark.asyncio
async def test_run_marks_failed_on_no_data(db_session: AsyncSession, tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    curves_root = tmp_path / "backtest_runs"

    profile = StrategyProfile(name="empty-profile", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()

    run = BacktestRun(
        profile_id=profile.id,
        profile_version=profile.version,
        profile_hash=_profile_hash(profile.config),
        strategy_name="buy_and_hold",
        venue="binance",
        symbols=["BTCUSDT"],
        start_ts=datetime(2024, 1, 1, tzinfo=UTC),
        end_ts=datetime(2024, 1, 31, tzinfo=UTC),
        status="pending",
    )
    db_session.add(run)
    await db_session.flush()

    service = BacktestService(
        session=db_session,
        parquet_root=parquet_root,
        backtest_curves_root=curves_root,
    )
    with pytest.raises(RuntimeError):  # BacktestDataError subclasses RuntimeError
        await service.execute(run.id)
    await db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_message is not None
