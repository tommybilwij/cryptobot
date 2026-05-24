"""Binance user-data stream WebSocket client.

Connects to ``wss://stream.binance.com:9443/ws/<listenKey>``. The listenKey is
obtained via REST POST /api/v3/userDataStream (requires API key). Phase 8: ships
the WS plumbing; listenKey lifecycle (60-min keepalive PUT) is caller's
responsibility — runner can call ``refresh_listen_key()`` every 30 min.

User-data events that matter: ``executionReport`` (e=executionReport). Fill events
have ``x=TRADE`` and ``X=FILLED`` or ``X=PARTIALLY_FILLED``.
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

_FILL_EXEC_TYPE = "TRADE"
_FILLED_STATUS = "FILLED"
_PARTIALLY_FILLED_STATUS = "PARTIALLY_FILLED"


class BinanceWSDisconnected(RuntimeError):
    """WebSocket dropped; caller should reconnect."""


class BinanceWSClient:
    name = "binance"

    def __init__(self, *, listen_key: str, base_url: str = "wss://stream.binance.com:9443") -> None:
        self._listen_key = listen_key
        self._base = base_url
        self._ws: ClientConnection | None = None

    async def connect(self) -> None:
        url = f"{self._base}/ws/{self._listen_key}"
        self._ws = await ws_connect(url)

    async def subscribe(self, *, stream: str) -> None:
        # Binance user-data is subscribed-by-path; no extra subscribe message
        _ = stream

    async def iter_messages(self) -> AsyncIterator[dict[str, Any]]:
        if self._ws is None:
            raise BinanceWSDisconnected("connect first")
        try:
            async for raw in self._ws:
                text = raw.decode() if isinstance(raw, bytes) else raw
                yield json.loads(text)
        except ConnectionClosed as e:
            raise BinanceWSDisconnected(str(e)) from e

    async def next_fill_for(
        self, order_id: str, *, timeout_s: float
    ) -> dict[str, Any] | None:
        try:
            async with asyncio.timeout(timeout_s):
                async for msg in self.iter_messages():
                    if msg.get("e") != "executionReport":
                        continue
                    if str(msg.get("i")) != order_id:  # i = orderId
                        continue
                    exec_type = msg.get("x")
                    status = msg.get("X")
                    if exec_type == _FILL_EXEC_TYPE and status in (
                        _FILLED_STATUS, _PARTIALLY_FILLED_STATUS,
                    ):
                        return msg
        except TimeoutError:
            return None
        return None

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
