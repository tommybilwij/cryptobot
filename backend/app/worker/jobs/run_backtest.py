"""Worker job — execute a queued BacktestRun by id."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session_factory
from app.logging_config import setup_logging
from app.services.backtest_service import BacktestService

logger = logging.getLogger(__name__)

_DEFAULT_PARQUET_ROOT = Path("data/parquet")
_DEFAULT_CURVES_ROOT = Path("data/backtest_runs")


async def run_with(
    *,
    session: AsyncSession,
    run_id: uuid.UUID,
    parquet_root: Path,
    curves_root: Path,
) -> None:
    """Execute a backtest run end-to-end against the given session.

    Pure dependency-injected entry point so tests can drive it with a fake
    session / fixture paths; ``run`` builds the real wiring.
    """
    service = BacktestService(
        session=session,
        parquet_root=parquet_root,
        backtest_curves_root=curves_root,
    )
    await service.execute(run_id)


async def run() -> None:
    """Entry point invoked by worker.main when WORKER_JOB=run_backtest.

    Reads ``BACKTEST_ID`` from the environment, opens a session via
    ``get_session_factory``, delegates to ``run_with``, and commits.

    Raises:
        KeyError: If ``BACKTEST_ID`` env var is unset.
    """
    setup_logging()
    raw_id = os.environ.get("BACKTEST_ID")
    if not raw_id:
        raise KeyError("BACKTEST_ID env var required for run_backtest job")
    run_id = uuid.UUID(raw_id)
    parquet_root = Path(os.environ.get("BACKTEST_PARQUET_ROOT", str(_DEFAULT_PARQUET_ROOT)))
    curves_root = Path(os.environ.get("BACKTEST_CURVES_ROOT", str(_DEFAULT_CURVES_ROOT)))

    factory = get_session_factory()
    async with factory() as session:
        await run_with(
            session=session,
            run_id=run_id,
            parquet_root=parquet_root,
            curves_root=curves_root,
        )
        await session.commit()
    logger.info("run_backtest complete", extra={"backtest_id": str(run_id)})
