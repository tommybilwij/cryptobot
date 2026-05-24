"""BinanceWSClient stub — real implementation is Phase 11+ slow-test scope.

Phase 11 ships the Protocol + paper impl. Real venue WS calibration requires
testnet WebSocket connectivity which is opt-in.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


class BinanceWSClient:
    name = "binance"

    async def connect(self) -> None:
        raise NotImplementedError("Phase 11+ scope")

    async def subscribe(self, *, stream: str) -> None:
        raise NotImplementedError("Phase 11+ scope")

    async def iter_messages(self) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError("Phase 11+ scope")
        yield  # pragma: no cover  # makes this an async generator

    async def next_fill_for(
        self, order_id: str, *, timeout_s: float
    ) -> dict[str, Any] | None:
        raise NotImplementedError("Phase 11+ scope")

    async def close(self) -> None:
        raise NotImplementedError("Phase 11+ scope")
