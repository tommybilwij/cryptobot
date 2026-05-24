"""Binance listen-key keepalive task (PUT every 30 min).

Binance user-data WebSocket streams are gated by a listenKey that is created
via ``POST /api/v3/userDataStream`` and expires after 60 minutes of inactivity.
To keep the key alive while a long-running WS connection is open the caller
must issue a ``PUT /api/v3/userDataStream?listenKey=...`` periodically. This
module ships the periodic-task wrapper; the listenKey itself is provisioned
by the caller and passed in.

Cadence: 30 minutes, half the expiry budget — single missed refresh still
leaves a wide margin before the key drops.

Failure handling: refresh errors are logged but do not stop the loop. If the
listenKey is revoked server-side, ``BinanceWSClient.iter_messages`` will
raise ``BinanceWSDisconnected`` on the WS leg and the runner reconnects with
a fresh key — the keepalive is a best-effort guard, not the source of truth.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.market_data._http import RetryingFetcher

logger = logging.getLogger(__name__)

_DEFAULT_REFRESH_INTERVAL_S = 1800.0  # 30 min
_DEFAULT_TIMEOUT_S = 10.0


class ListenKeyKeepalive:
    """Periodic PUT loop that extends a Binance listenKey's TTL."""

    def __init__(
        self,
        *,
        fetcher: RetryingFetcher,
        api_key: str,
        listen_key: str,
        base_url: str,
        interval_s: float = _DEFAULT_REFRESH_INTERVAL_S,
    ) -> None:
        # ``fetcher`` is held for retry/backoff parity with the rest of the
        # exchange layer; the PUT itself uses httpx directly because Binance
        # treats PUT /userDataStream as a keepalive that returns 200 with an
        # empty body — outside the JSON-fetch contract of ``RetryingFetcher``.
        self._fetcher = fetcher
        self._api_key = api_key
        self._listen_key = listen_key
        self._base = base_url.rstrip("/")
        self._interval = interval_s
        self._stopped = False

    def stop(self) -> None:
        """Signal the run loop to exit after its current sleep."""
        self._stopped = True

    async def run(self) -> None:
        """Refresh-then-sleep loop until ``stop()`` is called."""
        while not self._stopped:
            try:
                await self._refresh()
            except Exception:  # noqa: BLE001
                # Don't let a transient network error kill the keepalive —
                # the next iteration retries. WS disconnect is the real
                # signal that the key has died.
                logger.exception("listen-key refresh failed; will retry")
            await asyncio.sleep(self._interval)

    async def _refresh(self) -> None:
        url = f"{self._base}/api/v3/userDataStream?listenKey={self._listen_key}"
        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers={"X-MBX-APIKEY": self._api_key},
                timeout=_DEFAULT_TIMEOUT_S,
            )
            response.raise_for_status()
