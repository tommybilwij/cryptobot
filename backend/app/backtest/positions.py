"""PositionBook — applies fills to maintain open positions; marks them to market."""

from __future__ import annotations

from app.backtest.orders import Fill
from app.backtest.state import MarketSnapshot, Position, Product

_PositionKey = tuple[str, str, Product]


class PositionBook:
    """Mutable book of open positions keyed by (venue, symbol, product)."""

    def __init__(self) -> None:
        self._positions: dict[_PositionKey, Position] = {}

    def apply(self, fills: list[Fill]) -> None:
        for fill in fills:
            order = fill.order
            key: _PositionKey = (order.venue, order.symbol, order.product)
            delta = fill.qty_base_signed
            existing = self._positions.get(key)
            if existing is None:
                self._positions[key] = Position(
                    venue=order.venue,
                    symbol=order.symbol,
                    product=order.product,
                    qty_base=delta,
                    avg_entry_px=fill.fill_px,
                )
                continue
            new_qty = existing.qty_base + delta
            if new_qty == 0.0:
                del self._positions[key]
                continue
            same_sign = (delta * existing.qty_base) > 0
            if same_sign:
                # adding to position → weighted average entry
                new_avg = (
                    (existing.avg_entry_px * abs(existing.qty_base)) + (fill.fill_px * abs(delta))
                ) / (abs(existing.qty_base) + abs(delta))
                self._positions[key] = Position(
                    venue=existing.venue,
                    symbol=existing.symbol,
                    product=existing.product,
                    qty_base=new_qty,
                    avg_entry_px=new_avg,
                )
            else:
                # partial close → keep avg_entry
                self._positions[key] = Position(
                    venue=existing.venue,
                    symbol=existing.symbol,
                    product=existing.product,
                    qty_base=new_qty,
                    avg_entry_px=existing.avg_entry_px,
                )

    def snapshot(self) -> tuple[Position, ...]:
        return tuple(self._positions.values())

    def mark_to_market(self, snapshot: MarketSnapshot) -> float:
        total = 0.0
        for pos in self._positions.values():
            key: _PositionKey = (pos.venue, pos.symbol, pos.product)
            bar = snapshot.bars.get(key)
            if bar is None:
                continue
            total += pos.qty_base * bar.close
        return total
