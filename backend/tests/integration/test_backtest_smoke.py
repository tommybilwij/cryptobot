"""Integration smoke: BuyAndHold over real Binance Vision BTCUSDT 2024-01.

Marked ``slow`` (deselected by default). Requires:
  1. Phase 3 data refresh has populated data/parquet/binance/BTCUSDT/kline_1m/2024/01.parquet
  2. Postgres up + migrated to 0003

Run via: cd backend && uv run pytest -m slow tests/integration/test_backtest_smoke.py -v
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.parquet_store import DataType
from app.models.backtest_run import BacktestRun
from app.models.strategy_profile import StrategyProfile
from app.services.backtest_service import BacktestService


def _canonical_hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_smoke_buy_and_hold_btcusdt_jan_2024(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    parquet_root = Path("data/parquet")
    expected = (
        parquet_root / "binance" / "BTCUSDT" / DataType.KLINE_1M.value / "2024" / "01.parquet"
    )
    if not expected.exists():
        pytest.skip(f"requires Phase 3 data at {expected}")

    profile = StrategyProfile(name="smoke-buyhold", version=1, is_active=False, config={})
    db_session.add(profile)
    await db_session.flush()
    await db_session.commit()

    run = BacktestRun(
        profile_id=profile.id,
        profile_version=1,
        profile_hash=_canonical_hash({}),
        strategy_name="buy_and_hold",
        venue="binance",
        symbols=["BTCUSDT"],
        start_ts=datetime(2024, 1, 1, tzinfo=UTC),
        end_ts=datetime(2024, 1, 31, 23, 59, tzinfo=UTC),
        status="pending",
    )
    db_session.add(run)
    await db_session.flush()
    await db_session.commit()

    curves = tmp_path / "curves"
    service = BacktestService(
        session=db_session,
        parquet_root=parquet_root,
        backtest_curves_root=curves,
    )
    await service.execute(run.id)
    await db_session.refresh(run)
    assert run.status == "complete"
    assert run.num_trades is not None and run.num_trades >= 1
    assert run.equity_curve_path is not None
