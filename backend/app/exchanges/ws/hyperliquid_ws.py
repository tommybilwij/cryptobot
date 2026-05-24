"""Hyperliquid WebSocket client (wss://api.hyperliquid.xyz/ws).

HL doesn't require WS auth for public streams; for user-specific feeds (orderUpdates,
userFills) the subscribe message includes the user's address.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


class HyperliquidWSDisconnected(RuntimeError):
    pass


class HyperliquidWSClient:
    name = "hyperliquid"

    def __init__(
        self,
        *,
        user_address: str,
        base_url: str = "wss://api.hyperliquid.xyz/ws",
    ) -> None:
        self._user = user_address
        self._base = base_url
        self._ws: ClientConnection | None = None

    async def connect(self) -> None:
        self._ws = await ws_connect(self._base)

    async def subscribe(self, *, stream: str) -> None:
        if self._ws is None:
            raise HyperliquidWSDisconnected("connect first")
        # stream is the subscription type, e.g. "userFills"
        sub_msg = {
            "method": "subscribe",
            "subscription": {"type": stream, "user": self._user},
        }
        await self._ws.send(json.dumps(sub_msg))

    async def iter_messages(self) -> AsyncIterator[dict[str, Any]]:
        if self._ws is None:
            raise HyperliquidWSDisconnected("connect first")
        try:
            async for raw in self._ws:
                text = raw.decode() if isinstance(raw, bytes) else raw
                yield json.loads(text)
        except ConnectionClosed as e:
            raise HyperliquidWSDisconnected(str(e)) from e

    async def next_fill_for(
        self, order_id: str, *, timeout_s: float
    ) -> dict[str, Any] | None:
        try:
            async with asyncio.timeout(timeout_s):
                async for msg in self.iter_messages():
                    channel = msg.get("channel", "")
                    if channel != "userFills":
                        continue
                    fills = msg.get("data", {}).get("fills", [])
                    for fill in fills:
                        if str(fill.get("oid")) == order_id:
                            return dict(fill)
        except TimeoutError:
            return None
        return None

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
