"""Tests for /api/v1/metrics endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_metrics_returns_prometheus_format(async_client: AsyncClient) -> None:
    r = await async_client.get("/api/v1/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    body = r.text
    assert "cryptobot_up 1" in body
    assert "cryptobot_decision_audit_total" in body
    assert "cryptobot_backtest_runs_total" in body
    assert "cryptobot_oms_kill_switch_active" in body


@pytest.mark.asyncio
async def test_metrics_includes_help_and_type_lines(async_client: AsyncClient) -> None:
    r = await async_client.get("/api/v1/metrics")
    body = r.text
    assert "# HELP cryptobot_up" in body
    assert "# TYPE cryptobot_up gauge" in body
