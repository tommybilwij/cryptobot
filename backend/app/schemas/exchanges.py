"""Pydantic v2 schemas for exchange health endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class VenueHealth(BaseModel):
    name: str
    configured: bool
    use_testnet: bool
    reachable: bool
    balance_quote: float | None
    error: str | None


class ExchangesHealthResponse(BaseModel):
    venues: list[VenueHealth]
