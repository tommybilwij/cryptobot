"""Pydantic v2 schemas for OMS endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class KillRequest(BaseModel):
    reason: str | None = None


class KillResponse(BaseModel):
    active_profile_id: str
    kill_switch_active: bool
    new_version: int


class VenueStatus(BaseModel):
    name: str
    configured: bool
    use_testnet: bool


class OMSStatusResponse(BaseModel):
    kill_switch_active: bool
    active_profile_id: str | None
    active_profile_version: int | None
    last_dispatch_ts: datetime | None
    last_reconciliation_status: str | None
    venues: list[VenueStatus]
