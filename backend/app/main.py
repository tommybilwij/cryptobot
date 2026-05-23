"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from app.api import health
from app.deps import lifespan

app = FastAPI(title="cryptobot", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
