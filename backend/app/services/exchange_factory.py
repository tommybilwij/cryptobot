"""Adapter factory — dry-run-aware Exchange builder.

Returns PaperExchange in dry-run mode OR a real adapter built from env keys.
Falls back to PaperExchange when env keys are missing (defence in depth).
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.exchanges.base import Exchange
from app.exchanges.binance import BinanceExchange
from app.exchanges.bybit import BybitExchange
from app.exchanges.hyperliquid import HyperliquidExchange
from app.exchanges.paper import PaperExchange
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams

logger = logging.getLogger(__name__)

_DEFAULT_INITIAL_CASH = 10_000.0


def build_exchange(  # noqa: PLR0911 — one return per venue branch + paper fallback is clearest here
    venue: str,
    *,
    params: ProfileParams,
    fetcher: RetryingFetcher,
    settings: Settings,
    dry_run: bool,
) -> Exchange:
    if dry_run:
        return PaperExchange(venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH)

    if venue not in ("binance", "bybit", "hyperliquid"):
        raise ValueError(f"unknown venue: {venue}")

    use_testnet = bool(params.get(f"exchanges.{venue}.use_testnet"))

    if venue == "binance":
        if not settings.binance_api_key or not settings.binance_api_secret:
            logger.warning("binance keys missing; falling back to paper")
            return PaperExchange(venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH)
        url_key = (
            "exchanges.binance.spot_base_url_testnet" if use_testnet
            else "exchanges.binance.spot_base_url_mainnet"
        )
        return BinanceExchange(
            fetcher=fetcher, params=params,
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            base_url=str(params.get(url_key)),
        )

    if venue == "bybit":
        if not settings.bybit_api_key or not settings.bybit_api_secret:
            logger.warning("bybit keys missing; falling back to paper")
            return PaperExchange(venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH)
        url_key = (
            "exchanges.bybit.base_url_testnet" if use_testnet
            else "exchanges.bybit.base_url_mainnet"
        )
        return BybitExchange(
            fetcher=fetcher, params=params,
            api_key=settings.bybit_api_key,
            api_secret=settings.bybit_api_secret,
            base_url=str(params.get(url_key)),
        )

    if venue == "hyperliquid":
        if not settings.hyperliquid_wallet_private_key:
            logger.warning("hyperliquid key missing; falling back to paper")
            return PaperExchange(venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH)
        url_key = (
            "exchanges.hyperliquid.base_url_testnet" if use_testnet
            else "exchanges.hyperliquid.base_url_mainnet"
        )
        return HyperliquidExchange(
            fetcher=fetcher, params=params,
            wallet_private_key=settings.hyperliquid_wallet_private_key,
            base_url=str(params.get(url_key)),
        )

    raise ValueError(f"unknown venue: {venue}")
