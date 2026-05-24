"""LLM overlay — Anthropic-gated final pass on quantitative scores.

For symbols passing the quant threshold, asks Claude to veto/neutral/boost.
Falls back to ``decision="neutral"`` when API key is missing (no-op gate).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

from anthropic import AsyncAnthropic

from app.config import Settings
from app.profile.params import ProfileParams
from app.services.scoring import CompositeScore

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-opus-4-7"
_MAX_TOKENS = 500
_DEFAULT_VERDICT_DECISION: Literal["veto", "neutral", "boost"] = "neutral"


@dataclass(frozen=True)
class LLMVerdict:
    symbol: str
    decision: Literal["veto", "neutral", "boost"]
    confidence: float
    rationale: str


class LLMOverlay:
    def __init__(self, *, settings: Settings, params: ProfileParams) -> None:
        self._settings = settings
        self._params = params
        self._client: AsyncAnthropic | None = None
        if settings.anthropic_api_key:
            self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def assess(
        self,
        *,
        symbol: str,
        score: CompositeScore,
        context: dict[str, Any],
    ) -> LLMVerdict:
        if self._client is None:
            return LLMVerdict(
                symbol=symbol,
                decision=_DEFAULT_VERDICT_DECISION,
                confidence=0.0,
                rationale="anthropic_api_key not configured; LLM overlay skipped",
            )

        prompt = self._build_prompt(symbol, score, context)
        try:
            response = await self._client.messages.create(
                model=_DEFAULT_MODEL,
                max_tokens=_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            return self._parse_verdict(symbol, response)
        except Exception:  # noqa: BLE001
            logger.exception("LLM overlay call failed; defaulting to neutral")
            return LLMVerdict(
                symbol=symbol,
                decision=_DEFAULT_VERDICT_DECISION,
                confidence=0.0,
                rationale="LLM call failed",
            )

    def _build_prompt(
        self,
        symbol: str,
        score: CompositeScore,
        context: dict[str, Any],
    ) -> str:
        components_summary = "\n".join(
            f"  - {c.name}: raw={c.raw:.4f}, score={c.score:.4f}, weighted={c.weighted:.4f}"
            for c in score.components
        )
        return (
            f"You are a quant overlay agent for a crypto trading bot.\n\n"
            f"Symbol: {symbol}\n"
            f"Composite score: {score.total:.4f} (bucket: {score.bucket})\n"
            f"Components:\n{components_summary}\n\n"
            f"Context:\n{json.dumps(context, indent=2, default=str)}\n\n"
            f"Decide: veto (skip this signal), neutral (pass through), "
            f"or boost (increase priority). Respond with a single JSON object: "
            f'{{"decision": "veto|neutral|boost", "confidence": 0..1, "rationale": "..."}}'
        )

    def _parse_verdict(self, symbol: str, response: Any) -> LLMVerdict:
        try:
            text_block = response.content[0]
            raw_text = text_block.text if hasattr(text_block, "text") else str(text_block)
            parsed = json.loads(raw_text)
            decision_raw = str(parsed.get("decision", "neutral")).lower()
            if decision_raw not in ("veto", "neutral", "boost"):
                decision_raw = "neutral"
            decision: Literal["veto", "neutral", "boost"] = decision_raw  # type: ignore[assignment]
            return LLMVerdict(
                symbol=symbol,
                decision=decision,
                confidence=float(parsed.get("confidence", 0.5)),
                rationale=str(parsed.get("rationale", "")),
            )
        except (ValueError, KeyError, IndexError, AttributeError):
            return LLMVerdict(
                symbol=symbol,
                decision=_DEFAULT_VERDICT_DECISION,
                confidence=0.0,
                rationale="failed to parse LLM response",
            )
