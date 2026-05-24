"""HTTP API for exchange adapter health."""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db
from app.market_data._http import RetryingFetcher
from app.models.strategy_profile import StrategyProfile
from app.profile.params import ProfileParams
from app.schemas.exchanges import ExchangesHealthResponse, VenueHealth
from app.services.exchange_factory import build_exchange

router = APIRouter(prefix="/api/v1/exchanges", tags=["exchanges"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

_VENUES: tuple[str, ...] = ("binance", "bybit", "hyperliquid")


async def _active_profile(db: AsyncSession) -> StrategyProfile | None:
    result = await db.execute(select(StrategyProfile).where(StrategyProfile.is_active.is_(True)))
    return result.scalar_one_or_none()


@router.get("/health", response_model=ExchangesHealthResponse)
async def health(db: DbSession) -> ExchangesHealthResponse:
    """Per-venue reachability + USDC balance probe.

    Phase 9: adapters come from ``exchange_factory.build_exchange`` which
    returns a real Binance/Bybit/Hyperliquid adapter when env keys are
    configured and dry-run is off, or a ``PaperExchange`` otherwise. The
    factory's defence-in-depth fallback means missing env keys gracefully
    degrade to paper rather than 500 the endpoint.
    """
    profile = await _active_profile(db)
    config = profile.config if profile else {}
    params = ProfileParams(profile=config)
    dry_run = bool(params.get("live.dry_run_mode"))
    venues: list[VenueHealth] = []
    # One httpx.AsyncClient + RetryingFetcher per request — adapters that
    # actually do network I/O share it; PaperExchange ignores it.
    async with httpx.AsyncClient() as http_client:
        fetcher = RetryingFetcher(client=http_client, base_backoff_s=0.0)
        for name in _VENUES:
            use_testnet = bool(params.get(f"exchanges.{name}.use_testnet"))
            adapter = build_exchange(
                name,
                params=params,
                fetcher=fetcher,
                settings=settings,
                dry_run=dry_run,
            )
            try:
                balance = await adapter.fetch_balance("USDC")
            except Exception as e:  # noqa: BLE001 — surfacing the failure mode is the point
                venues.append(
                    VenueHealth(
                        name=name,
                        configured=False,
                        use_testnet=use_testnet,
                        reachable=False,
                        balance_quote=None,
                        error=f"{type(e).__name__}: {e}",
                    )
                )
                continue
            venues.append(
                VenueHealth(
                    name=name,
                    configured=True,
                    use_testnet=use_testnet,
                    reachable=True,
                    balance_quote=balance.free,
                    error=None,
                )
            )
    return ExchangesHealthResponse(venues=venues)
