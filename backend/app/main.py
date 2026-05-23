"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from app.api import health

app = FastAPI(title="cryptobot", version="0.1.0")
app.include_router(health.router)
