"""Tests for BybitPublicClient."""

from __future__ import annotations

import gzip
import io

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.market_data._http import RetryingFetcher
from app.market_data.bybit_public import BybitPublicClient


def _gzip(s: str) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(s.encode())
    return buf.getvalue()


@pytest.mark.asyncio
async def test_fetch_klines_1m_parses_csvgz() -> None:
    csv = (
        "start_at,open,high,low,close,volume,turnover\n"
        "1714521600,60000,60015,59995,60010,10.5,630074\n"
        "1714521660,60010,60025,60005,60020,11.0,660209\n"
    )
    body = _gzip(csv)

    def handler(req: Request) -> Response:
        assert "BTCUSDT" in req.url.path
        return Response(200, content=body)

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        client = BybitPublicClient(fetcher=fetcher)
        df = await client.fetch_klines_1m("BTCUSDT", 2026, 4)

    assert df.height == 2
    assert df.columns == ["ts_ms", "open", "high", "low", "close", "volume"]
    # Bybit uses seconds; client must convert to ms
    assert df["ts_ms"][0] == 1714521600000
