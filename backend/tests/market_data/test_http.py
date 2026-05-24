"""Tests for shared HTTP fetcher (retry + rate-limit backoff)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.market_data._http import RetryingFetcher


@pytest.mark.asyncio
async def test_fetcher_returns_body_on_200() -> None:
    def handler(req: Request) -> Response:
        return Response(200, content=b"hello")

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=3, base_backoff_s=0.0)
        body = await fetcher.get_bytes("https://example.com/data.zip")
    assert body == b"hello"


@pytest.mark.asyncio
async def test_fetcher_retries_on_429() -> None:
    calls = {"n": 0}

    def handler(req: Request) -> Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return Response(429, content=b"slow down")
        return Response(200, content=b"ok")

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=5, base_backoff_s=0.0)
        body = await fetcher.get_bytes("https://example.com/data.zip")
    assert body == b"ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_fetcher_raises_on_404() -> None:
    def handler(req: Request) -> Response:
        return Response(404, content=b"not found")

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=3, base_backoff_s=0.0)
        with pytest.raises(FileNotFoundError):
            await fetcher.get_bytes("https://example.com/missing.zip")


@pytest.mark.asyncio
async def test_fetcher_gives_up_after_max_retries() -> None:
    def handler(req: Request) -> Response:
        return Response(503, content=b"try again later")

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=2, base_backoff_s=0.0)
        with pytest.raises(RuntimeError):
            await fetcher.get_bytes("https://example.com/data.zip")


@pytest.mark.asyncio
async def test_fetcher_get_json_returns_dict() -> None:
    def handler(req: Request) -> Response:
        return Response(200, json={"hello": "world"})

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=3, base_backoff_s=0.0)
        body = await fetcher.get_json("https://example.com/data")
    assert body == {"hello": "world"}


@pytest.mark.asyncio
async def test_fetcher_post_json_sends_body_and_returns_response() -> None:
    captured = {}

    def handler(req: Request) -> Response:
        assert req.method == "POST"
        import json

        captured["body"] = json.loads(req.content)
        return Response(200, json={"ok": True})

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=3, base_backoff_s=0.0)
        body = await fetcher.post_json("https://example.com/place", body={"foo": "bar"})
    assert body == {"ok": True}
    assert captured["body"] == {"foo": "bar"}


@pytest.mark.asyncio
async def test_fetcher_post_passes_headers() -> None:
    captured = {}

    def handler(req: Request) -> Response:
        captured["headers"] = dict(req.headers)
        return Response(200, json={})

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, base_backoff_s=0.0)
        await fetcher.post_json(
            "https://example.com/place",
            body={"x": 1},
            headers={"X-API-KEY": "abc"},
        )
    assert captured["headers"].get("x-api-key") == "abc"
