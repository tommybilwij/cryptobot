"""Worker entry point.

Started via: `python -m app.worker.main` (or via docker-compose `worker` service).
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 30.0


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
    asyncio.run(heartbeat())


if __name__ == "__main__":
    main()
