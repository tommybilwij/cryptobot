"""Tests for the worker heartbeat stub."""

from __future__ import annotations

import pytest

from app.worker.main import heartbeat


@pytest.mark.asyncio
async def test_heartbeat_runs_for_max_iterations(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO"):
        n = await heartbeat(interval_s=0.0, max_iterations=3)
    assert n == 3
    heartbeat_logs = [r for r in caplog.records if "worker heartbeat" in r.message]
    assert len(heartbeat_logs) == 3


@pytest.mark.asyncio
async def test_heartbeat_zero_iterations() -> None:
    n = await heartbeat(interval_s=0.0, max_iterations=0)
    assert n == 0
