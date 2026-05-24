"""Tests for PaperWSClient."""

from __future__ import annotations

import pytest

from app.exchanges.ws.paper_ws import PaperWSClient


@pytest.mark.asyncio
async def test_connect_and_close() -> None:
    ws = PaperWSClient()
    await ws.connect()
    await ws.close()


@pytest.mark.asyncio
async def test_next_fill_returns_matching_order() -> None:
    ws = PaperWSClient()
    await ws.connect()
    ws.push({"order_id": "abc", "fill_px": 60000.0, "qty": 0.1})
    msg = await ws.next_fill_for("abc", timeout_s=1.0)
    assert msg is not None
    assert msg["fill_px"] == 60000.0


@pytest.mark.asyncio
async def test_next_fill_returns_none_on_timeout() -> None:
    ws = PaperWSClient()
    await ws.connect()
    msg = await ws.next_fill_for("xyz", timeout_s=0.05)
    assert msg is None


@pytest.mark.asyncio
async def test_next_fill_skips_unmatched_messages() -> None:
    ws = PaperWSClient()
    await ws.connect()
    ws.push({"order_id": "wrong", "fill_px": 1.0})
    ws.push({"order_id": "right", "fill_px": 2.0})
    msg = await ws.next_fill_for("right", timeout_s=1.0)
    assert msg is not None
    assert msg["fill_px"] == 2.0
