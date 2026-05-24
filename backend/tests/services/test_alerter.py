"""Tests for the Alerter webhook service.

Three properties:
  1. Empty ``alerts.webhook_url`` → no HTTP call (true no-op).
  2. Non-empty URL → POSTs a payload with the documented shape.
  3. Webhook failures NEVER propagate to the runner.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams
from app.services.alerter import Alerter


@pytest.mark.asyncio
async def test_alerter_no_url_is_noop() -> None:
    """Empty webhook URL → handler is never invoked."""
    calls = {"n": 0}

    def handler(req: Request) -> Response:
        calls["n"] += 1
        return Response(200, json={"ok": True})

    params = ProfileParams(profile={})  # default alerts.webhook_url == ""

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=0, base_backoff_s=0.0)
        alerter = Alerter(params=params, fetcher=fetcher)
        await alerter.send(severity="critical", event="DrawdownBrakeHalt", details={"x": 1})

    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_alerter_posts_payload() -> None:
    """Webhook URL set → POST body has severity/event/details/ts keys."""
    captured: dict[str, object] = {}

    def handler(req: Request) -> Response:
        assert req.method == "POST"
        captured["body"] = json.loads(req.content)
        return Response(200, json={"ok": True})

    params = ProfileParams(profile={"alerts": {"webhook_url": "https://hooks.example.com/abc"}})

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=0, base_backoff_s=0.0)
        alerter = Alerter(params=params, fetcher=fetcher)
        await alerter.send(
            severity="critical",
            event="DrawdownBrakeHalt",
            details={"drawdown_pct": 0.06},
        )

    body = captured["body"]
    assert isinstance(body, dict)
    assert set(body.keys()) == {"severity", "event", "details", "ts"}
    assert body["severity"] == "critical"
    assert body["event"] == "DrawdownBrakeHalt"
    assert body["details"] == {"drawdown_pct": 0.06}
    assert isinstance(body["ts"], str) and body["ts"]  # ISO timestamp present


@pytest.mark.asyncio
async def test_alerter_swallows_post_failure() -> None:
    """500 from webhook → send returns cleanly, no exception bubbles up."""

    def handler(req: Request) -> Response:
        return Response(500, content=b"webhook down")

    params = ProfileParams(profile={"alerts": {"webhook_url": "https://hooks.example.com/abc"}})

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=0, base_backoff_s=0.0)
        alerter = Alerter(params=params, fetcher=fetcher)
        # MUST NOT raise; runner cannot be disrupted by webhook flakiness.
        await alerter.send(severity="warning", event="HedgeDriftHalt", details={})
