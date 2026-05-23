"""Tests for BinanceVisionClient."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.market_data._http import RetryingFetcher
from app.market_data.binance_vision import BinanceVisionClient

FIXTURES = Path(__file__).parent / "fixtures"


def _zip_bytes(csv_bytes: bytes, name: str) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, csv_bytes)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_fetch_klines_1m_parses_csv() -> None:
    raw_csv = (FIXTURES / "binance_klines_sample.csv").read_bytes()
    zipped = _zip_bytes(raw_csv, "BTCUSDT-1m-2026-04.csv")

    def handler(req: Request) -> Response:
        assert "BTCUSDT" in req.url.path
        assert "1m" in req.url.path
        assert "2026-04" in req.url.path
        return Response(200, content=zipped)

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        client = BinanceVisionClient(fetcher=fetcher)
        df = await client.fetch_klines_1m("BTCUSDT", 2026, 4)

    assert isinstance(df, pl.DataFrame)
    assert df.height == 3
    assert df.columns == ["ts_ms", "open", "high", "low", "close", "volume"]
    assert df["ts_ms"].to_list() == [1714521600000, 1714521660000, 1714521720000]
    assert df["open"].to_list() == [60000.0, 60010.0, 60020.0]


@pytest.mark.asyncio
async def test_fetch_klines_1m_missing_month_raises() -> None:
    def handler(req: Request) -> Response:
        return Response(404, content=b"not found")

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, max_retries=1, base_backoff_s=0.0)
        client = BinanceVisionClient(fetcher=fetcher)
        with pytest.raises(FileNotFoundError):
            await client.fetch_klines_1m("BTCUSDT", 2030, 12)


@pytest.mark.asyncio
async def test_fetch_funding_rates_parses_csv() -> None:
    raw_csv = (FIXTURES / "binance_funding_sample.csv").read_bytes()
    zipped = _zip_bytes(raw_csv, "BTCUSDT-fundingRate-2026-04.csv")

    def handler(req: Request) -> Response:
        assert "fundingRate" in req.url.path
        return Response(200, content=zipped)

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        client = BinanceVisionClient(fetcher=fetcher)
        df = await client.fetch_funding_rates("BTCUSDT", 2026, 4)

    assert df.height == 3
    assert df.columns == ["ts_ms", "predicted", "realized"]
    assert df["realized"].to_list() == [0.0001, 0.000125, 0.00009]


@pytest.mark.asyncio
async def test_fetch_open_interest_parses_csv() -> None:
    raw_csv = (FIXTURES / "binance_oi_sample.csv").read_bytes()
    zipped = _zip_bytes(raw_csv, "BTCUSDT-metrics-2026-04.csv")

    def handler(req: Request) -> Response:
        assert "metrics" in req.url.path
        return Response(200, content=zipped)

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        client = BinanceVisionClient(fetcher=fetcher)
        df = await client.fetch_open_interest("BTCUSDT", 2026, 4)

    assert df.height == 2
    assert df.columns == ["ts_ms", "oi_base", "oi_quote"]
    assert df["oi_base"].to_list() == [12345.5, 12350.0]
