"""FactorPortfolioStrategy — long top-decile (optionally short bottom-decile).

Phase 15 ships the strategy. Feature pipelines (rolling vol, cross-sectional
volume rank) are simplified for now; Phase 16+ wires real implementations.

Sizing per position: cash / target_count (equal weight).
"""

from __future__ import annotations

from typing import Literal, cast

from app.backtest.orders import Order
from app.backtest.state import MarketState, Position
from app.profile.params import ProfileParams
from app.services.scoring import CompositeScore, ScoringEngine


class FactorPortfolioStrategy:
    name = "factor_portfolio"

    def __init__(self, *, venue: str, universe: list[str]) -> None:
        self._venue = venue
        self._universe = universe

    def evaluate(self, state: MarketState, params: ProfileParams) -> list[Order]:
        if not self._universe:
            return []

        target_longs, target_shorts, target_count = self._compute_targets(state, params)

        current_longs = self._current_symbols(state.positions, sign=1)
        current_shorts = self._current_symbols(state.positions, sign=-1)

        orders: list[Order] = []
        orders.extend(self._close_orders(state.positions, current_longs - target_longs))
        orders.extend(self._close_orders(state.positions, current_shorts - target_shorts))

        cash_per_position = state.cash_quote / target_count if target_count > 0 else 0.0
        orders.extend(
            self._open_orders(state, target_longs - current_longs, cash_per_position, "buy")
        )
        orders.extend(
            self._open_orders(state, target_shorts - current_shorts, cash_per_position, "sell")
        )
        return orders

    def _compute_targets(
        self, state: MarketState, params: ProfileParams
    ) -> tuple[set[str], set[str], int]:
        scoring = ScoringEngine(params=params)
        top_decile_pct = float(params.get("strategies.factor_portfolio.top_decile_pct"))
        shorts_enabled = float(params.get("strategies.factor_portfolio.shorts_enabled")) > 0.0

        scores: list[CompositeScore] = []
        for symbol in self._universe:
            features = self._features(state, symbol, params)
            scores.append(scoring.score(symbol=symbol, features=features))
        scores.sort(key=lambda s: s.total, reverse=True)

        target_count = max(1, int(len(self._universe) * top_decile_pct))
        target_longs = {s.symbol for s in scores[:target_count]}
        target_shorts: set[str] = set()
        if shorts_enabled:
            bottom_decile_pct = float(params.get("strategies.factor_portfolio.bottom_decile_pct"))
            short_count = max(1, int(len(self._universe) * bottom_decile_pct))
            target_shorts = {s.symbol for s in scores[-short_count:]}
        return target_longs, target_shorts, target_count

    def _current_symbols(self, positions: tuple[Position, ...], *, sign: int) -> set[str]:
        """Symbols of spot positions whose qty_base has the requested sign."""
        result: set[str] = set()
        for p in positions:
            if p.venue != self._venue or p.product != "spot":
                continue
            if sign > 0 and p.qty_base > 0.0:
                result.add(p.symbol)
            elif sign < 0 and p.qty_base < 0.0:
                result.add(p.symbol)
        return result

    def _close_orders(self, positions: tuple[Position, ...], symbols: set[str]) -> list[Order]:
        orders: list[Order] = []
        for symbol in symbols:
            pos = self._find_position(positions, symbol, "spot")
            if pos is not None and pos.qty_base != 0.0:
                orders.append(self._close_order(symbol, "spot", pos))
        return orders

    def _open_orders(
        self,
        state: MarketState,
        symbols: set[str],
        cash_per_position: float,
        side: Literal["buy", "sell"],
    ) -> list[Order]:
        orders: list[Order] = []
        for symbol in symbols:
            bar = state.snapshot.bars.get((self._venue, symbol, "spot"))
            if bar is None or bar.close <= 0.0:
                continue
            qty = cash_per_position / bar.close
            if qty > 0.0:
                orders.append(
                    Order(
                        venue=self._venue,
                        symbol=symbol,
                        product="spot",
                        side=side,
                        qty_base=qty,
                        order_type="market",
                    )
                )
        return orders

    def _features(self, state: MarketState, symbol: str, params: ProfileParams) -> dict[str, float]:
        """Build feature dict for one symbol from the market state.

        Phase 15 simplification: only ``funding_yield`` is wired to real data.
        Other components default to 0.0 — Phase 16+ adds proper pipelines
        (rolling realized vol, cross-sectional volume rank, momentum_30d).

        HP1: funding annualisation uses the per-venue cadence
        (``exchanges.{venue}.funding_intervals_per_year``) so HL's hourly
        funding doesn't get scaled under Binance's 8h assumption.
        """
        features: dict[str, float] = {}
        funding = state.snapshot.funding_rates.get((self._venue, symbol))
        if funding is not None:
            intervals_per_year_key = f"exchanges.{self._venue}.funding_intervals_per_year"
            intervals_per_year = float(params.get(intervals_per_year_key))
            features["funding_yield"] = funding * intervals_per_year
        return features

    def _find_position(
        self, positions: tuple[Position, ...], symbol: str, product: str
    ) -> Position | None:
        for p in positions:
            if p.venue == self._venue and p.symbol == symbol and p.product == product:
                return p
        return None

    def _close_order(self, symbol: str, product: str, pos: Position) -> Order:
        side: Literal["buy", "sell"] = "sell" if pos.qty_base > 0.0 else "buy"
        product_lit = cast("Literal['spot','perp']", product)
        return Order(
            venue=self._venue,
            symbol=symbol,
            product=product_lit,
            side=side,
            qty_base=abs(pos.qty_base),
            order_type="market",
        )
