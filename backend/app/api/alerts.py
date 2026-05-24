"""Webhook self-test endpoint."""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.market_data._http import RetryingFetcher
from app.models.strategy_profile import StrategyProfile
from app.profile.params import ProfileParams
from app.services.alerter import Alerter

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class AlertTestResponse(BaseModel):
    sent: bool
    webhook_url_configured: bool
    error: str | None = None


@router.post("/test", response_model=AlertTestResponse)
async def test_webhook(db: DbSession) -> AlertTestResponse:
    """Fires a synthetic 'info' alert through the configured webhook."""
    result = await db.execute(
        select(StrategyProfile).where(StrategyProfile.is_active.is_(True))
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no active profile")
    params = ProfileParams(profile=profile.config)
    url = str(params.get("alerts.webhook_url"))
    if not url:
        return AlertTestResponse(sent=False, webhook_url_configured=False)
    async with httpx.AsyncClient() as client:
        fetcher = RetryingFetcher(client=client, base_backoff_s=0.0)
        alerter = Alerter(params=params, fetcher=fetcher)
        try:
            await alerter.send(
                severity="info",
                event="webhook_self_test",
                details={"message": "preflight test from /api/v1/alerts/test"},
            )
        except Exception as e:  # noqa: BLE001
            return AlertTestResponse(
                sent=False,
                webhook_url_configured=True,
                error=str(e),
            )
    return AlertTestResponse(sent=True, webhook_url_configured=True)
