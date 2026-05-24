"""Pydantic v2 schemas for backtest endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class CreateBacktestRequest(BaseModel):
    profile_id: uuid.UUID
    strategy_name: Annotated[str, Field(min_length=1, max_length=80)]
    start_ts: datetime
    end_ts: datetime
    venue: Annotated[str, Field(min_length=1, max_length=40)]
    symbols: Annotated[list[str], Field(min_length=1, max_length=200)]

    @field_validator("end_ts")
    @classmethod
    def _end_after_start(cls, v: datetime, info: ValidationInfo) -> datetime:
        start = info.data.get("start_ts")
        if start is not None and v <= start:
            raise ValueError("end_ts must be after start_ts")
        return v


class BacktestResponse(BaseModel):
    id: uuid.UUID
    profile_id: uuid.UUID
    profile_version: int
    profile_hash: str
    strategy_name: str
    venue: str
    symbols: list[str]
    start_ts: datetime
    end_ts: datetime
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    total_return: float | None
    sharpe: float | None
    max_drawdown: float | None
    num_trades: int | None
    equity_curve_path: str | None
    error_message: str | None
    created_at: datetime
