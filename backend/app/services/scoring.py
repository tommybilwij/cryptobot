"""Composite scoring engine — weighted-sum factor scores for Strategy B.

Each component has a registry-driven max_score (raw → normalised clamp) and
weight (normalised score → weighted contribution). Final composite total maps
to a bucket via the existing `strategies.factor_portfolio.scoring.thresholds.*`
registry block.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.profile.params import ProfileParams

_COMPONENT_NAMES = ("momentum_30d", "funding_yield", "realized_vol", "volume_rank")


@dataclass(frozen=True)
class ComponentScore:
    name: str
    raw: float
    score: float
    weight: float
    weighted: float


@dataclass(frozen=True)
class CompositeScore:
    symbol: str
    total: float
    components: tuple[ComponentScore, ...]
    bucket: str


class ScoringEngine:
    def __init__(self, *, params: ProfileParams) -> None:
        self._params = params

    def score(self, *, symbol: str, features: dict[str, float]) -> CompositeScore:
        components: list[ComponentScore] = []
        total = 0.0
        for name in _COMPONENT_NAMES:
            raw = features.get(name, 0.0)
            max_s = float(self._params.get(f"strategies.factor_portfolio.scoring.{name}.max_score"))
            weight = float(self._params.get(f"strategies.factor_portfolio.scoring.{name}.weight"))
            score = self._normalise(name, raw, max_s)
            weighted = score * weight
            components.append(
                ComponentScore(
                    name=name,
                    raw=raw,
                    score=score,
                    weight=weight,
                    weighted=weighted,
                )
            )
            total += weighted

        bucket = self._bucket(total)
        return CompositeScore(
            symbol=symbol,
            total=total,
            components=tuple(components),
            bucket=bucket,
        )

    def _normalise(self, name: str, raw: float, max_score: float) -> float:
        """Linear clamp into [-max_score, +max_score].

        For ``realized_vol``, lower is better — invert sign before clamp.
        """
        if name == "realized_vol":
            # Lower vol → higher score. Centre around 0.5 (50% annual vol).
            centred = 0.5 - raw
            return max(-max_score, min(max_score, centred * max_score * 2.0))
        return max(-max_score, min(max_score, raw * max_score))

    def _bucket(self, total: float) -> str:
        strong_buy = float(
            self._params.get("strategies.factor_portfolio.scoring.thresholds.strong_buy")
        )
        buy = float(self._params.get("strategies.factor_portfolio.scoring.thresholds.buy"))
        watch = float(self._params.get("strategies.factor_portfolio.scoring.thresholds.watch"))
        if total >= strong_buy:
            return "strong_buy"
        if total >= buy:
            return "buy"
        if total >= watch:
            return "watch"
        if total >= 0.0:
            return "neutral"
        return "skip"
