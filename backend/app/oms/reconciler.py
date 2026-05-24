"""PositionReconciler — halt-class drift detection.

Two checks per dispatch:
  1. Book vs exchange — our PositionBook's qty must match what the exchange reports.
     Drift > ``oms.reconcile_drift_halt_pct`` raises ``ReconciliationDriftHalt``.
  2. Hedge consistency — for symbols with both spot + perp positions, the qty
     magnitudes must match (delta-neutral). Drift > ``oms.hedge_drift_halt_pct``
     raises ``HedgeDriftHalt``.
"""

from __future__ import annotations

from app.backtest.state import Position
from app.exchanges.types import ExchangePosition
from app.oms.exceptions import HedgeDriftHalt, ReconciliationDriftHalt
from app.profile.params import ProfileParams

_EPSILON = 1e-9


class PositionReconciler:
    def __init__(self, *, params: ProfileParams) -> None:
        self._params = params

    def check_book_vs_exchange(
        self,
        *,
        book_positions: tuple[Position, ...],
        exchange_positions: tuple[ExchangePosition, ...],
    ) -> None:
        threshold = float(self._params.get("oms.reconcile_drift_halt_pct"))
        book_map: dict[tuple[str, str, str], float] = {
            (p.venue, p.symbol, p.product): p.qty_base for p in book_positions
        }
        ex_map: dict[tuple[str, str, str], float] = {
            (p.venue, p.symbol, p.product): p.qty_base for p in exchange_positions
        }
        for key, book_qty in book_map.items():
            if abs(book_qty) < _EPSILON:
                continue
            ex_qty = ex_map.get(key, 0.0)
            diff = abs(book_qty - ex_qty)
            pct = diff / max(abs(book_qty), _EPSILON)
            if pct > threshold:
                raise ReconciliationDriftHalt(
                    f"book vs exchange drift {pct:.4f} on {key}: "
                    f"book={book_qty}, exchange={ex_qty}, threshold={threshold}"
                )

    def check_hedge_consistency(
        self,
        *,
        positions: tuple[Position, ...],
    ) -> None:
        threshold = float(self._params.get("oms.hedge_drift_halt_pct"))
        by_symbol: dict[tuple[str, str], dict[str, float]] = {}
        for p in positions:
            key = (p.venue, p.symbol)
            by_symbol.setdefault(key, {})[p.product] = p.qty_base
        for (venue, symbol), products in by_symbol.items():
            if "spot" not in products or "perp" not in products:
                continue
            spot_qty = abs(products["spot"])
            perp_qty = abs(products["perp"])
            if spot_qty < _EPSILON:
                continue
            drift_pct = abs(spot_qty - perp_qty) / spot_qty
            if drift_pct > threshold:
                raise HedgeDriftHalt(
                    f"hedge drift {drift_pct:.4f} on {venue}/{symbol}: "
                    f"|spot|={spot_qty}, |perp|={perp_qty}, threshold={threshold}"
                )
