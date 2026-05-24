"""Pydantic v2 schemas for decision-audit endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DecisionAuditResponse(BaseModel):
    id: uuid.UUID
    ts: datetime
    strategy_name: str
    profile_id: uuid.UUID
    profile_version: int
    profile_hash: str
    decision_type: str
    input_state: dict[str, Any]
    orders: list[Any]
    fills: list[Any]
    reconciliation_status: str
    reason: str | None
    created_at: datetime
