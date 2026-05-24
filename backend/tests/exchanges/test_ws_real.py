"""Tests for real WS clients using mocked websockets."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.exchanges.ws.binance_ws import BinanceWSClient
from app.exchanges.ws.bybit_ws import BybitWSClient
from app.exchanges.ws.hyperliquid_ws import HyperliquidWSClient


class _FakeWS:
    """Drop-in replacement for websockets ClientConnection."""

    def __init__(self, messages: list[dict]) -> None:
        self._messages = [json.dumps(m) for m in messages]
        self._idx = 0
        self.sent: list[str] = []

    async def send(self, msg: str) -> None:
        self.sent.append(msg)

    async def close(self) -> None:
        pass

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self._idx >= len(self._messages):
            raise StopAsyncIteration
        msg = self._messages[self._idx]
        self._idx += 1
        return msg


@pytest.mark.asyncio
async def test_binance_ws_finds_matching_fill() -> None:
    fake = _FakeWS([
        {"e": "executionReport", "i": 999, "x": "TRADE", "X": "FILLED"},
    ])
    ws = BinanceWSClient(listen_key="abc")
    with patch("app.exchanges.ws.binance_ws.ws_connect", AsyncMock(return_value=fake)):
        await ws.connect()
    msg = await ws.next_fill_for("999", timeout_s=1.0)
    assert msg is not None
    assert msg["X"] == "FILLED"


@pytest.mark.asyncio
async def test_binance_ws_skips_non_fill_messages() -> None:
    fake = _FakeWS([
        {"e": "heartbeat"},
        {"e": "executionReport", "i": 999, "x": "NEW", "X": "NEW"},
        {"e": "executionReport", "i": 999, "x": "TRADE", "X": "FILLED"},
    ])
    ws = BinanceWSClient(listen_key="abc")
    with patch("app.exchanges.ws.binance_ws.ws_connect", AsyncMock(return_value=fake)):
        await ws.connect()
    msg = await ws.next_fill_for("999", timeout_s=1.0)
    assert msg is not None
    assert msg["x"] == "TRADE"


@pytest.mark.asyncio
async def test_bybit_ws_auth_message_sent_on_connect() -> None:
    fake = _FakeWS([])
    ws = BybitWSClient(api_key="key", api_secret="secret")
    with patch("app.exchanges.ws.bybit_ws.ws_connect", AsyncMock(return_value=fake)):
        await ws.connect()
    # Verify auth message was sent
    assert len(fake.sent) == 1
    auth = json.loads(fake.sent[0])
    assert auth["op"] == "auth"
    assert auth["args"][0] == "key"


@pytest.mark.asyncio
async def test_bybit_ws_finds_fill_in_execution_topic() -> None:
    fake = _FakeWS([
        {
            "topic": "execution.linear",
            "data": [{"orderId": "abc-123", "execPrice": "60000"}],
        },
    ])
    ws = BybitWSClient(api_key="k", api_secret="s")
    with patch("app.exchanges.ws.bybit_ws.ws_connect", AsyncMock(return_value=fake)):
        await ws.connect()
    msg = await ws.next_fill_for("abc-123", timeout_s=1.0)
    assert msg is not None
    assert msg["execPrice"] == "60000"


@pytest.mark.asyncio
async def test_hyperliquid_ws_subscribes_with_user_address() -> None:
    fake = _FakeWS([])
    ws = HyperliquidWSClient(user_address="0xabc")
    with patch("app.exchanges.ws.hyperliquid_ws.ws_connect", AsyncMock(return_value=fake)):
        await ws.connect()
        await ws.subscribe(stream="userFills")
    sub = json.loads(fake.sent[0])
    assert sub["method"] == "subscribe"
    assert sub["subscription"]["user"] == "0xabc"


@pytest.mark.asyncio
async def test_hyperliquid_ws_finds_fill_by_oid() -> None:
    fake = _FakeWS([
        {"channel": "userFills", "data": {"fills": [{"oid": 42, "px": "60100"}]}},
    ])
    ws = HyperliquidWSClient(user_address="0xabc")
    with patch("app.exchanges.ws.hyperliquid_ws.ws_connect", AsyncMock(return_value=fake)):
        await ws.connect()
    msg = await ws.next_fill_for("42", timeout_s=1.0)
    assert msg is not None
    assert msg["px"] == "60100"
