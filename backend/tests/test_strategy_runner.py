"""Tests for the strategy-runner heartbeat stub."""
from __future__ import annotations

import pytest

from app.strategy_runner.main import run


@pytest.mark.asyncio
async def test_run_with_max_iterations(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO"):
        n = await run(
            strategy_name="funding_arb",
            interval_s=0.0,
            max_iterations=2,
        )
    assert n == 2
    heartbeat_logs = [
        r for r in caplog.records if "strategy-runner heartbeat" in r.message
    ]
    assert len(heartbeat_logs) == 2


@pytest.mark.asyncio
async def test_run_logs_strategy_name(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        await run(
            strategy_name="factor_portfolio",
            interval_s=0.0,
            max_iterations=1,
        )
    record = [r for r in caplog.records if "strategy-runner heartbeat" in r.message][0]
    assert record.strategy == "factor_portfolio"
