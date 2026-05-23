"""Refresh-data worker job — pulls latest klines for the active universe."""

from __future__ import annotations

import logging
from datetime import datetime

from app.services.data_pipeline import DataPipelineService

logger = logging.getLogger(__name__)


async def run_with(
    *,
    pipeline: DataPipelineService,
    exchange: str,
    symbols: list[str],
    now: datetime,
) -> None:
    """Refresh the current month's 1m klines for every symbol in the universe.

    Pure dependency-injected entry point so tests can drive it with a fake
    pipeline; ``run`` builds the real wiring.
    """
    for symbol in symbols:
        await pipeline.refresh_klines_1m(
            exchange=exchange, symbol=symbol, year=now.year, month=now.month
        )
        logger.info(
            "refresh_data: wrote partition",
            extra={"exchange": exchange, "symbol": symbol},
        )


async def run() -> None:
    """Entry point invoked by worker.main when WORKER_JOB=refresh_data.

    Reads active profile to determine the universe, builds a real pipeline,
    delegates to run_with. Kept thin so unit tests can drive run_with directly.
    """
    # Wiring happens in a later task (real DB session + profile lookup); for now,
    # log that the job ran with no work to do.
    logger.info("refresh_data: stub run — no active profile loaded yet")
