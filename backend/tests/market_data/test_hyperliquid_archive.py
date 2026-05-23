"""Tests for HyperliquidArchiveClient."""

from __future__ import annotations

import gzip
import io

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.market_data._http import RetryingFetcher
from app.market_data.hyperliquid_archive import HyperliquidArchiveClient


def _gzip_jsonl(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write("\n".join(lines).encode())
    return buf.getvalue()


@pytest.mark.asyncio
async def test_fetch_klines_1m_aggregates_from_trades() -> None:
    # Two trades in the same minute, one in the next
    trades = [
        '{"time": 1714521600123, "coin": "BTC", "px": "60000", "sz": "0.5"}',
        '{"time": 1714521610456, "coin": "BTC", "px": "60010", "sz": "0.3"}',
        '{"time": 1714521660789, "coin": "BTC", "px": "60020", "sz": "0.2"}',
    ]
    body = _gzip_jsonl(trades)

    def handler(req: Request) -> Response:
        return Response(200, content=body)

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        client = HyperliquidArchiveClient(fetcher=fetcher)
        df = await client.fetch_klines_1m("BTC", 2026, 4)

    assert df.height == 2
    assert df.columns == ["ts_ms", "open", "high", "low", "close", "volume"]
    assert df["open"][0] == 60000.0
    assert df["close"][0] == 60010.0
    assert df["volume"][0] == 0.8
