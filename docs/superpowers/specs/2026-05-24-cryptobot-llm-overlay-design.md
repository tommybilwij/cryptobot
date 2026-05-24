# Cryptobot Phase 17 — LLM Overlay Design Spec

**Date**: 2026-05-24
**Phase**: 17

## Goal

Add an **LLM-gated final pass** on top of `ScoringEngine`'s output: for symbols that pass the quantitative bar (composite score ≥ `llm_gate` threshold), call Anthropic's API with a structured prompt asking "veto, neutral, or boost this signal?". Returns a `LLMVerdict`. FactorPortfolioStrategy uses verdicts to filter the top-decile before opening positions.

Pattern: stockbot's LLM-overlay calls Claude with company-specific structured prompts.

## Architecture

`backend/app/services/llm_overlay.py`:

```python
@dataclass(frozen=True)
class LLMVerdict:
    symbol: str
    decision: Literal["veto", "neutral", "boost"]
    confidence: float    # 0..1
    rationale: str       # short LLM-provided text

class LLMOverlay:
    def __init__(self, *, settings: Settings, params: ProfileParams) -> None: ...
    
    async def assess(self, *, symbol: str, score: CompositeScore, context: dict[str, Any]) -> LLMVerdict: ...
```

Uses `anthropic` Python SDK (NEW dep). API key from `Settings.anthropic_api_key`. If key missing → returns `decision="neutral"` (no-op fallback).

`LLMVerdict.decision`:
- `"veto"` → skip this symbol regardless of composite score
- `"neutral"` → pass through unchanged
- `"boost"` → bump priority (Phase 17 doesn't act on boost yet; reserved for future bucketing logic)

## Components

- `backend/pyproject.toml` — add `anthropic>=0.40` dep
- `backend/app/config.py` — `anthropic_api_key: str = ""` field
- `backend/app/services/llm_overlay.py` — `LLMOverlay` service
- `backend/tests/services/test_llm_overlay.py` — 4 tests (mocked Anthropic client)

## DoD

~284 tests pass. LLMOverlay returns LLMVerdict from a mocked Anthropic response; falls back to "neutral" when API key missing.
