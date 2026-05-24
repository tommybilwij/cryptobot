"""Tests for LLMOverlay."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.profile.params import ProfileParams
from app.services.llm_overlay import LLMOverlay
from app.services.scoring import ComponentScore, CompositeScore


def _settings(api_key: str = "") -> Settings:
    return Settings(
        _env_file=None,
        binance_api_key="",
        binance_api_secret="",
        bybit_api_key="",
        bybit_api_secret="",
        hyperliquid_wallet_private_key="",
        anthropic_api_key=api_key,
    )


def _score() -> CompositeScore:
    return CompositeScore(
        symbol="BTCUSDT",
        total=8.5,
        components=(
            ComponentScore(name="momentum_30d", raw=0.3, score=1.5, weight=0.3, weighted=0.45),
        ),
        bucket="buy",
    )


@pytest.mark.asyncio
async def test_no_api_key_returns_neutral() -> None:
    overlay = LLMOverlay(settings=_settings(""), params=ProfileParams(profile={}))
    verdict = await overlay.assess(
        symbol="BTCUSDT",
        score=_score(),
        context={},
    )
    assert verdict.decision == "neutral"
    assert verdict.confidence == 0.0
    assert "not configured" in verdict.rationale


@pytest.mark.asyncio
async def test_successful_llm_call_parses_verdict() -> None:
    overlay = LLMOverlay(settings=_settings("test-key"), params=ProfileParams(profile={}))
    # Mock the Anthropic client to return a structured response
    mock_response = MagicMock()
    text_block = MagicMock()
    text_block.text = '{"decision": "boost", "confidence": 0.85, "rationale": "strong setup"}'
    mock_response.content = [text_block]

    with patch.object(
        overlay._client,
        "messages",
        AsyncMock(create=AsyncMock(return_value=mock_response)),
    ):
        verdict = await overlay.assess(
            symbol="BTCUSDT",
            score=_score(),
            context={"foo": "bar"},
        )
    assert verdict.decision == "boost"
    assert verdict.confidence == 0.85
    assert verdict.rationale == "strong setup"


@pytest.mark.asyncio
async def test_malformed_response_falls_back_to_neutral() -> None:
    overlay = LLMOverlay(settings=_settings("test-key"), params=ProfileParams(profile={}))
    mock_response = MagicMock()
    text_block = MagicMock()
    text_block.text = "not json at all"
    mock_response.content = [text_block]

    with patch.object(
        overlay._client,
        "messages",
        AsyncMock(create=AsyncMock(return_value=mock_response)),
    ):
        verdict = await overlay.assess(
            symbol="BTCUSDT",
            score=_score(),
            context={},
        )
    assert verdict.decision == "neutral"


@pytest.mark.asyncio
async def test_api_call_failure_returns_neutral() -> None:
    overlay = LLMOverlay(settings=_settings("test-key"), params=ProfileParams(profile={}))
    with patch.object(
        overlay._client,
        "messages",
        AsyncMock(create=AsyncMock(side_effect=RuntimeError("API down"))),
    ):
        verdict = await overlay.assess(
            symbol="BTCUSDT",
            score=_score(),
            context={},
        )
    assert verdict.decision == "neutral"
    assert "failed" in verdict.rationale
