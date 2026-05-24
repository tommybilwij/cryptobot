"""WSClient Protocol — push-based fill stream from exchange WS."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol


class WSClient(Protocol):
    name: str

    async def connect(self) -> None: ...
    async def subscribe(self, *, stream: str) -> None: ...
    async def iter_messages(self) -> AsyncIterator[dict[str, Any]]: ...
    async def next_fill_for(
        self, order_id: str, *, timeout_s: float
    ) -> dict[str, Any] | None: ...
    async def close(self) -> None: ...
