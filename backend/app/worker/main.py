"""Worker entry point.

Started via: ``python -m app.worker.main`` (or via docker-compose ``worker`` service).

If env var ``WORKER_JOB`` is set, dispatch to the named job in
``app.worker.jobs.*`` and exit. Otherwise, run the heartbeat loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Coroutine
from typing import Any

from app.worker.jobs import refresh_data, run_backtest

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 30.0

_JOBS: dict[str, Callable[[], Coroutine[Any, Any, None]]] = {
    "refresh_data": refresh_data.run,
    "run_backtest": run_backtest.run,
}


def _resolve_job(name: str) -> Callable[[], Coroutine[Any, Any, None]]:
    """Look up a registered worker job by name.

    Args:
        name: Job identifier (matches ``WORKER_JOB`` env var).

    Returns:
        The async callable entry point for the job.

    Raises:
        KeyError: If ``name`` is not registered in ``_JOBS``.
    """
    if name not in _JOBS:
        raise KeyError(f"unknown worker job: {name}")
    return _JOBS[name]


async def heartbeat(
    *,
    interval_s: float = HEARTBEAT_INTERVAL_S,
    max_iterations: int | None = None,
) -> int:
    """Background heartbeat loop.

    Args:
        interval_s: Seconds between heartbeats.
        max_iterations: Optional cap (for tests). None = infinite.

    Returns:
        Number of iterations completed.
    """
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        logger.info("worker heartbeat", extra={"iteration": iterations})
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        await asyncio.sleep(interval_s)
    return iterations


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    job_name = os.environ.get("WORKER_JOB")
    if job_name:
        job = _resolve_job(job_name)
        asyncio.run(job())
    else:
        asyncio.run(heartbeat())


if __name__ == "__main__":
    main()
