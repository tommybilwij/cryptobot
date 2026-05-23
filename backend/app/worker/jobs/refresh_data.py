"""Refresh-data worker job — pulls latest klines/funding for the active universe."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run() -> None:
    """Placeholder until Task 18 wires this up to the active profile."""
    logger.info("refresh_data: stub run (no work yet)")
