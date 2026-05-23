"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from app.api import data_health, health, strategy_profiles
from app.deps import lifespan

app = FastAPI(title="cryptobot", version="0.3.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(strategy_profiles.router)
app.include_router(data_health.router)
