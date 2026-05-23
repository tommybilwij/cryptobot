"""Strategy-runner entry point.

Started via: `python -m app.strategy_runner.main --strategy-name funding_arb`
(or via docker-compose `strategy-runner-*` services).
"""

from __future__ import annotations

import argparse
import asyncio
import logging

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 30.0


async def run(
    *,
    strategy_name: str,
    interval_s: float = HEARTBEAT_INTERVAL_S,
    max_iterations: int | None = None,
) -> int:
    """Per-strategy heartbeat loop.

    Args:
        strategy_name: identifier (e.g. 'funding_arb', 'factor_portfolio').
        interval_s: Seconds between heartbeats.
        max_iterations: Optional cap (for tests). None = infinite.

    Returns:
        Number of iterations completed.
    """
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        logger.info(
            "strategy-runner heartbeat",
            extra={"strategy": strategy_name, "iteration": iterations},
        )
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        await asyncio.sleep(interval_s)
    return iterations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy-name", required=True)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run(strategy_name=args.strategy_name))


if __name__ == "__main__":
    main()
