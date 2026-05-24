"""Tests for /api/v1/backtests endpoints."""

from __future__ import annotations

import uuid as _uuid
from pathlib import Path

import polars as pl
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.parquet_store import ParquetStore
from app.models.strategy_profile import StrategyProfile


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
async def test_post_creates_pending_row(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _write_klines(parquet_root)
    monkeypatch.setenv("BACKTEST_PARQUET_ROOT", str(parquet_root))

    profile = StrategyProfile(name="test-api1", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    body = {
        "profile_id": str(profile.id),
        "strategy_name": "buy_and_hold",
        "start_ts": "2024-01-01T00:00:00Z",
        "end_ts": "2024-01-01T00:02:00Z",
        "venue": "binance",
        "symbols": ["BTCUSDT"],
    }
    r = await async_client.post("/api/v1/backtests", json=body)
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "pending"
    assert "id" in data
    assert data["profile_hash"]  # non-empty


@pytest.mark.asyncio
async def test_get_returns_row(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parquet_root = tmp_path / "parquet"
    parquet_root.mkdir()
    _write_klines(parquet_root)
    monkeypatch.setenv("BACKTEST_PARQUET_ROOT", str(parquet_root))

    profile = StrategyProfile(name="test-api2", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    body = {
        "profile_id": str(profile.id),
        "strategy_name": "buy_and_hold",
        "start_ts": "2024-01-01T00:00:00Z",
        "end_ts": "2024-01-01T00:02:00Z",
        "venue": "binance",
        "symbols": ["BTCUSDT"],
    }
    r = await async_client.post("/api/v1/backtests", json=body)
    run_id = r.json()["id"]
    g = await async_client.get(f"/api/v1/backtests/{run_id}")
    assert g.status_code == 200
    assert g.json()["id"] == run_id


@pytest.mark.asyncio
async def test_post_rejects_unknown_strategy(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    profile = StrategyProfile(name="test-api3", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    body = {
        "profile_id": str(profile.id),
        "strategy_name": "does_not_exist",
        "start_ts": "2024-01-01T00:00:00Z",
        "end_ts": "2024-01-01T00:02:00Z",
        "venue": "binance",
        "symbols": ["BTCUSDT"],
    }
    r = await async_client.post("/api/v1/backtests", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_unknown_profile(async_client: AsyncClient) -> None:
    body = {
        "profile_id": str(_uuid.uuid4()),
        "strategy_name": "buy_and_hold",
        "start_ts": "2024-01-01T00:00:00Z",
        "end_ts": "2024-01-01T00:02:00Z",
        "venue": "binance",
        "symbols": ["BTCUSDT"],
    }
    r = await async_client.post("/api/v1/backtests", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_missing_returns_404(async_client: AsyncClient) -> None:
    r = await async_client.get(f"/api/v1/backtests/{_uuid.uuid4()}")
    assert r.status_code == 404
