"""Tests for the dry-run-aware exchange factory.

Five properties:
  1. dry_run=True always returns PaperExchange (even with keys present).
  2. dry_run=False + missing keys falls back to PaperExchange + logs warning.
  3. dry_run=False + keys present builds the matching real adapter.
  4. Unknown venue raises ValueError.
  5. ``exchanges.{venue}.use_testnet`` flag selects the right base URL.
"""

from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.config import Settings
from app.exchanges.binance import BinanceExchange
from app.exchanges.paper import PaperExchange
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams
from app.services.exchange_factory import build_exchange


def _noop_handler(req: Request) -> Response:
    """Factory never makes HTTP calls; transport must exist for AsyncClient."""
    return Response(200, json={})


def _settings(**kw: str) -> Settings:
    """Build a Settings instance with all key fields explicitly set.

    ``_env_file=None`` ignores any local .env so tests are hermetic.
    """
    defaults = {
        "binance_api_key": "",
        "binance_api_secret": "",
        "bybit_api_key": "",
        "bybit_api_secret": "",
        "hyperliquid_wallet_private_key": "",
    }
    defaults.update(kw)
    return Settings(_env_file=None, **defaults)  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_factory_dry_run_returns_paper() -> None:
    """Even with real keys set, dry_run=True forces PaperExchange."""
    params = ProfileParams(profile={})
    settings = _settings(binance_api_key="x", binance_api_secret="y")

    async with AsyncClient(transport=MockTransport(_noop_handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=0, base_backoff_s=0.0)
        ex = build_exchange(
            "binance",
            params=params,
            fetcher=fetcher,
            settings=settings,
            dry_run=True,
        )

    assert isinstance(ex, PaperExchange)


@pytest.mark.asyncio
async def test_factory_missing_keys_falls_back_to_paper(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """dry_run=False with empty keys → PaperExchange + warning logged."""
    params = ProfileParams(profile={})
    settings = _settings()  # all keys empty

    async with AsyncClient(transport=MockTransport(_noop_handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=0, base_backoff_s=0.0)
        with caplog.at_level(logging.WARNING, logger="app.services.exchange_factory"):
            ex = build_exchange(
                "binance",
                params=params,
                fetcher=fetcher,
                settings=settings,
                dry_run=False,
            )

    assert isinstance(ex, PaperExchange)
    assert any("binance keys missing" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_factory_binance_with_keys_returns_real_adapter() -> None:
    """dry_run=False + binance keys → BinanceExchange instance."""
    params = ProfileParams(profile={})
    settings = _settings(binance_api_key="x", binance_api_secret="y")

    async with AsyncClient(transport=MockTransport(_noop_handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=0, base_backoff_s=0.0)
        ex = build_exchange(
            "binance",
            params=params,
            fetcher=fetcher,
            settings=settings,
            dry_run=False,
        )

    assert isinstance(ex, BinanceExchange)


@pytest.mark.asyncio
async def test_factory_unknown_venue_raises() -> None:
    """Unknown venue must raise ValueError — fail loudly, never default."""
    params = ProfileParams(profile={})
    settings = _settings(binance_api_key="x", binance_api_secret="y")

    async with AsyncClient(transport=MockTransport(_noop_handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=0, base_backoff_s=0.0)
        with pytest.raises(ValueError, match="unknown venue"):
            build_exchange(
                "unknown",
                params=params,
                fetcher=fetcher,
                settings=settings,
                dry_run=False,
            )


@pytest.mark.asyncio
async def test_factory_testnet_vs_mainnet_url() -> None:
    """Flipping exchanges.binance.use_testnet picks the mainnet URL."""
    # Mainnet: use_testnet=False → spot_base_url_mainnet
    mainnet_params = ProfileParams(
        profile={"exchanges": {"binance": {"use_testnet": False}}}
    )
    settings = _settings(binance_api_key="x", binance_api_secret="y")

    async with AsyncClient(transport=MockTransport(_noop_handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=0, base_backoff_s=0.0)
        ex = build_exchange(
            "binance",
            params=mainnet_params,
            fetcher=fetcher,
            settings=settings,
            dry_run=False,
        )

    assert isinstance(ex, BinanceExchange)
    # _base is set from base_url.rstrip("/"); confirm mainnet URL plumbed through.
    assert ex._base == "https://api.binance.com"

    # And the inverse: use_testnet=True (default) → testnet URL.
    testnet_params = ProfileParams(profile={})
    async with AsyncClient(transport=MockTransport(_noop_handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=0, base_backoff_s=0.0)
        ex2 = build_exchange(
            "binance",
            params=testnet_params,
            fetcher=fetcher,
            settings=settings,
            dry_run=False,
        )

    assert isinstance(ex2, BinanceExchange)
    assert ex2._base == "https://testnet.binance.vision"
