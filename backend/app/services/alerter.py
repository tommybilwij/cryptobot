"""Alerter — POSTs halt-class events to a webhook URL.

Empty ``alerts.webhook_url`` → no-op. Errors are caught + logged; alerter never
throws so the live runner is never disrupted by a flaky webhook.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams

logger = logging.getLogger(__name__)


class Alerter:
    def __init__(self, *, params: ProfileParams, fetcher: RetryingFetcher) -> None:
        self._params = params
        self._fetcher = fetcher

    async def send(self, *, severity: str, event: str, details: dict[str, Any]) -> None:
        url = str(self._params.get("alerts.webhook_url"))
        if not url:
            return
        payload: dict[str, object] = {
            "severity": severity,
            "event": event,
            "details": details,
            "ts": datetime.now(UTC).isoformat(),
        }
        try:
            await self._fetcher.post_json(url, body=payload)
        except Exception:  # noqa: BLE001
            logger.exception("alerter webhook failed; continuing")
