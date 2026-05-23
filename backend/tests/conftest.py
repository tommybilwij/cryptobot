"""Pytest fixtures for the cryptobot backend."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient


@pytest.fixture
def client() -> TestClient:
    """Synchronous TestClient — fine for endpoints that don't touch the DB."""
    from app.main import app

    return TestClient(app)


@pytest.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    """Async client for endpoints that touch the async DB session."""
    from app.main import app

    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c
