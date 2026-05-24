"""DecisionAuditService — write + query DecisionAuditEntry rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_audit import DecisionAuditEntry

_DEFAULT_LIMIT = 50


class DecisionAuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log_decision(
        self,
        *,
        ts: datetime,
        strategy_name: str,
        profile_id: uuid.UUID,
        profile_version: int,
        profile_hash: str,
        input_state: dict[str, Any],
        orders: list[Any],
        fills: list[Any],
        reconciliation_status: str,
        reason: str | None = None,
    ) -> DecisionAuditEntry:
        entry = DecisionAuditEntry(
            ts=ts,
            strategy_name=strategy_name,
            profile_id=profile_id,
            profile_version=profile_version,
            profile_hash=profile_hash,
            decision_type="order",
            input_state=input_state,
            orders=orders,
            fills=fills,
            reconciliation_status=reconciliation_status,
            reason=reason,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def log_snapshot(
        self,
        *,
        ts: datetime,
        strategy_name: str,
        profile_id: uuid.UUID,
        profile_version: int,
        profile_hash: str,
        input_state: dict[str, Any],
    ) -> DecisionAuditEntry:
        entry = DecisionAuditEntry(
            ts=ts,
            strategy_name=strategy_name,
            profile_id=profile_id,
            profile_version=profile_version,
            profile_hash=profile_hash,
            decision_type="snapshot",
            input_state=input_state,
            orders=[],
            fills=[],
            reconciliation_status="ok",
            reason=None,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def get_recent(
        self,
        *,
        limit: int = _DEFAULT_LIMIT,
        strategy_name: str | None = None,
        decision_type: str | None = None,
    ) -> list[DecisionAuditEntry]:
        stmt = select(DecisionAuditEntry).order_by(DecisionAuditEntry.ts.desc()).limit(limit)
        if strategy_name is not None:
            stmt = stmt.where(DecisionAuditEntry.strategy_name == strategy_name)
        if decision_type is not None:
            stmt = stmt.where(DecisionAuditEntry.decision_type == decision_type)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
