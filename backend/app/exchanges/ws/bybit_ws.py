"""Bybit V5 private WebSocket client (wss://stream.bybit.com/v5/private).

Auth: send {"op":"auth","args":[api_key, expires_ms, signature]} where
signature = HMAC_SHA256(api_secret, "GET/realtime" + expires_ms).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

_EXPIRES_OFFSET_MS = 10_000
_MS_PER_SECOND = 1000


class BybitWSDisconnected(RuntimeError):
    pass


class BybitWSClient:
    name = "bybit"

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str = "wss://stream.bybit.com/v5/private",
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._base = base_url
        self._ws: ClientConnection | None = None

    def _sign(self, expires_ms: int) -> str:
        payload = f"GET/realtime{expires_ms}"
        return hmac.new(
            self._api_secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()

    async def connect(self) -> None:
        self._ws = await ws_connect(self._base)
        expires_ms = int(time.time() * _MS_PER_SECOND) + _EXPIRES_OFFSET_MS
        auth_msg = {
            "op": "auth",
            "args": [self._api_key, expires_ms, self._sign(expires_ms)],
        }
        await self._ws.send(json.dumps(auth_msg))

    async def subscribe(self, *, stream: str) -> None:
        if self._ws is None:
            raise BybitWSDisconnected("connect first")
        await self._ws.send(json.dumps({"op": "subscribe", "args": [stream]}))

    async def iter_messages(self) -> AsyncIterator[dict[str, Any]]:
        if self._ws is None:
            raise BybitWSDisconnected("connect first")
        try:
            async for raw in self._ws:
                text = raw.decode() if isinstance(raw, bytes) else raw
                yield json.loads(text)
        except ConnectionClosed as e:
            raise BybitWSDisconnected(str(e)) from e

    async def next_fill_for(
        self, order_id: str, *, timeout_s: float
    ) -> dict[str, Any] | None:
        try:
            async with asyncio.timeout(timeout_s):
                async for msg in self.iter_messages():
                    topic = msg.get("topic", "")
                    if not topic.startswith("execution"):
                        continue
                    for fill in msg.get("data", []):
                        if str(fill.get("orderId")) == order_id:
                            return dict(fill)
        except TimeoutError:
            return None
        return None

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
