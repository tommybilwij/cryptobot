"""Tests for worker job dispatch."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.worker.main import _resolve_job


def test_resolve_unknown_job_raises() -> None:
    with pytest.raises(KeyError):
        _resolve_job("does_not_exist")


def test_resolve_refresh_data_returns_callable() -> None:
    job = _resolve_job("refresh_data")
    assert callable(job)


@pytest.mark.asyncio
async def test_refresh_data_invokes_pipeline_per_symbol() -> None:
    from app.worker.jobs.refresh_data import run_with

    fake_pipeline = AsyncMock()
    now = datetime(2026, 5, 24, tzinfo=UTC)
    await run_with(
        pipeline=fake_pipeline,
        exchange="binance",
        symbols=["BTCUSDT", "ETHUSDT"],
        now=now,
    )
    assert fake_pipeline.refresh_klines_1m.call_count == 2
    call_args = [c.kwargs for c in fake_pipeline.refresh_klines_1m.call_args_list]
    assert {a["symbol"] for a in call_args} == {"BTCUSDT", "ETHUSDT"}
    assert all(a["year"] == 2026 and a["month"] == 5 for a in call_args)


@pytest.mark.asyncio
async def test_run_backtest_dispatches() -> None:
    from app.worker.main import _resolve_job

    job = _resolve_job("run_backtest")
    assert callable(job)


@pytest.mark.asyncio
async def test_run_backtest_requires_backtest_id_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BACKTEST_ID", raising=False)
    from app.worker.jobs.run_backtest import run

    with pytest.raises(KeyError, match="BACKTEST_ID"):
        await run()
