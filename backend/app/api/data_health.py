"""HTTP API for surfacing recent data-health events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.models.data_health_event import DataHealthEvent

router = APIRouter(prefix="/api/v1/data-health", tags=["data-health"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

_DEFAULT_LIMIT = 50


class DataHealthEventResponse(BaseModel):
    id: uuid.UUID
    ts: datetime
    event_type: str
    exchange: str
    symbol: str | None
    data_type: str | None
    severity: str
    details: dict[str, Any]
    description: str | None


@router.get("/recent", response_model=list[DataHealthEventResponse])
async def recent(db: DbSession, limit: int = _DEFAULT_LIMIT) -> list[DataHealthEventResponse]:
    result = await db.execute(
        select(DataHealthEvent).order_by(DataHealthEvent.ts.desc()).limit(limit)
    )
    rows = list(result.scalars().all())
    return [DataHealthEventResponse.model_validate(r, from_attributes=True) for r in rows]
