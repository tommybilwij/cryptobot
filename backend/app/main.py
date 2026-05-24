"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    backtests,
    data_health,
    decision_audit,
    exchanges,
    health,
    live,
    metrics,
    oms,
    strategy_profiles,
)
from app.deps import lifespan
from app.logging_config import setup_logging

setup_logging()

app = FastAPI(title="cryptobot", version="1.6.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(strategy_profiles.router)
app.include_router(data_health.router)
app.include_router(backtests.router)
app.include_router(oms.router)
app.include_router(decision_audit.router)
app.include_router(exchanges.router)
app.include_router(live.router)
app.include_router(metrics.router)
