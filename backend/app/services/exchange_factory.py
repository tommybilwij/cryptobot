"""Adapter factory — dry-run-aware Exchange builder.

Returns PaperExchange in dry-run mode OR a real adapter built from env keys.
Falls back to PaperExchange when env keys are missing (defence in depth).

Phase 13: ``sub_account`` kwarg routes to strategy-specific API key fields
(e.g. ``binance_api_key_funding_arb``). Falls back to the base field when
the sub-account key is empty so legacy single-key deployments keep working.
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


def _resolve_key(settings: Settings, base_field: str, sub_account: str | None) -> str:
    """Return sub-account key if present, else base key.

    The ``sub_account`` string is normalized (dashes → underscores) so that
    profile values like ``"strategy-a-arb"`` map to the field
    ``binance_api_key_strategy_a_arb``.
    """
    if sub_account is None:
        return str(getattr(settings, base_field, ""))
    normalized = sub_account.replace("-", "_")
    sub_field = f"{base_field}_{normalized}"
    sub_value = str(getattr(settings, sub_field, ""))
    if sub_value:
        return sub_value
    return str(getattr(settings, base_field, ""))


def build_exchange(  # noqa: PLR0911 — one return per venue branch + paper fallback is clearest here
    venue: str,
    *,
    params: ProfileParams,
    fetcher: RetryingFetcher,
    settings: Settings,
    dry_run: bool,
    sub_account: str | None = None,
) -> Exchange:
    if dry_run:
        return PaperExchange(venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH)

    if venue not in ("binance", "bybit", "hyperliquid"):
        raise ValueError(f"unknown venue: {venue}")

    use_testnet = bool(params.get(f"exchanges.{venue}.use_testnet"))

    if venue == "binance":
        api_key = _resolve_key(settings, "binance_api_key", sub_account)
        api_secret = _resolve_key(settings, "binance_api_secret", sub_account)
        if not api_key or not api_secret:
            logger.warning("binance keys missing; falling back to paper")
            return PaperExchange(venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH)
        url_key = (
            "exchanges.binance.spot_base_url_testnet"
            if use_testnet
            else "exchanges.binance.spot_base_url_mainnet"
        )
        return BinanceExchange(
            fetcher=fetcher,
            params=params,
            api_key=api_key,
            api_secret=api_secret,
            base_url=str(params.get(url_key)),
        )

    if venue == "bybit":
        api_key = _resolve_key(settings, "bybit_api_key", sub_account)
        api_secret = _resolve_key(settings, "bybit_api_secret", sub_account)
        if not api_key or not api_secret:
            logger.warning("bybit keys missing; falling back to paper")
            return PaperExchange(venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH)
        url_key = (
            "exchanges.bybit.base_url_testnet"
            if use_testnet
            else "exchanges.bybit.base_url_mainnet"
        )
        return BybitExchange(
            fetcher=fetcher,
            params=params,
            api_key=api_key,
            api_secret=api_secret,
            base_url=str(params.get(url_key)),
        )

    if venue == "hyperliquid":
        wallet_private_key = _resolve_key(settings, "hyperliquid_wallet_private_key", sub_account)
        if not wallet_private_key:
            logger.warning("hyperliquid key missing; falling back to paper")
            return PaperExchange(venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH)
        url_key = (
            "exchanges.hyperliquid.base_url_testnet"
            if use_testnet
            else "exchanges.hyperliquid.base_url_mainnet"
        )
        return HyperliquidExchange(
            fetcher=fetcher,
            params=params,
            wallet_private_key=wallet_private_key,
            base_url=str(params.get(url_key)),
        )

    raise ValueError(f"unknown venue: {venue}")
