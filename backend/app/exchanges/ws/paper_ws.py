"""PaperWSClient — in-memory queue for tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any


class PaperWSClient:
    name = "paper"

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def subscribe(self, *, stream: str) -> None:
        _ = stream  # paper ignores stream filter

    def push(self, message: dict[str, Any]) -> None:
        """Test helper: enqueue a message."""
        self._queue.put_nowait(message)

    async def iter_messages(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            msg = await self._queue.get()
            yield msg

    async def next_fill_for(
        self, order_id: str, *, timeout_s: float
    ) -> dict[str, Any] | None:
        try:
            while True:
                msg = await asyncio.wait_for(self._queue.get(), timeout=timeout_s)
                if msg.get("order_id") == order_id:
                    return msg
        except TimeoutError:
            return None

    async def close(self) -> None:
        self._connected = False
