"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from app.api import (
    backtests,
    data_health,
    decision_audit,
    exchanges,
    health,
    live,
    oms,
    strategy_profiles,
)
from app.deps import lifespan

app = FastAPI(title="cryptobot", version="0.7.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(strategy_profiles.router)
app.include_router(data_health.router)
app.include_router(backtests.router)
app.include_router(oms.router)
app.include_router(decision_audit.router)
app.include_router(exchanges.router)
app.include_router(live.router)
