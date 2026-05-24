"""HTTP API for recent decision-audit entries."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.schemas.decision_audit import DecisionAuditResponse
from app.services.decision_audit import DecisionAuditService

router = APIRouter(prefix="/api/v1/decision-audit", tags=["decision-audit"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

_DEFAULT_LIMIT = 50


@router.get("/recent", response_model=list[DecisionAuditResponse])
async def recent(
    db: DbSession,
    limit: int = _DEFAULT_LIMIT,
    strategy_name: str | None = None,
    decision_type: str | None = None,
) -> list[DecisionAuditResponse]:
    """Return the most recent decision-audit entries (optionally filtered)."""
    svc = DecisionAuditService(db)
    entries = await svc.get_recent(
        limit=limit,
        strategy_name=strategy_name,
        decision_type=decision_type,
    )
    return [
        DecisionAuditResponse.model_validate(e, from_attributes=True) for e in entries
    ]
