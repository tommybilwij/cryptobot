"""HTTP API for exchange adapter health."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.exchanges.paper import PaperExchange
from app.models.strategy_profile import StrategyProfile
from app.profile.params import ProfileParams
from app.schemas.exchanges import ExchangesHealthResponse, VenueHealth

router = APIRouter(prefix="/api/v1/exchanges", tags=["exchanges"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

_VENUES: tuple[str, ...] = ("binance", "bybit", "hyperliquid")
_INITIAL_CASH = 10_000.0


async def _active_profile(db: AsyncSession) -> StrategyProfile | None:
    result = await db.execute(
        select(StrategyProfile).where(StrategyProfile.is_active.is_(True))
    )
    return result.scalar_one_or_none()


@router.get("/health", response_model=ExchangesHealthResponse)
async def health(db: DbSession) -> ExchangesHealthResponse:
    """Per-venue reachability + USDC balance probe.

    Phase 7: the real adapters need env-keyed credentials that aren't wired
    yet, so each venue is pinged via ``PaperExchange``. Phase 8+ swaps in the
    real Binance/Bybit/Hyperliquid adapters when env keys are present and
    falls back to ``configured: false`` when they're not.
    """
    profile = await _active_profile(db)
    config = profile.config if profile else {}
    params = ProfileParams(profile=config)
    venues: list[VenueHealth] = []
    for name in _VENUES:
        use_testnet = bool(params.get(f"exchanges.{name}.use_testnet"))
        # Phase 7: ping via PaperExchange. Real adapters require env keys,
        # wired in Phase 8+ once a credential-loading layer exists.
        paper = PaperExchange(venue=name, params=params, initial_cash=_INITIAL_CASH)
        try:
            balance = await paper.fetch_balance("USDC")
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
