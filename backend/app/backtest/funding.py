"""FundingLedger — applies perp funding payments at venue-defined cadence.

Convention: positive funding rate means longs pay shorts.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from app.backtest.state import Position


@dataclass(frozen=True)
class FundingEvent:
    ts_ms: int
    venue: str
    symbol: str
    position_qty: float
    funding_rate: float
    mark_px: float
    payment_quote: float


class FundingLedger:
    """Stateless: events_for(...) is called once per tick by the engine."""

    def events_for(
        self,
        *,
        positions: tuple[Position, ...],
        ts_ms: int,
        funding_data: dict[tuple[str, str], pl.DataFrame],
        mark_pxs: dict[tuple[str, str, str], float],
    ) -> list[FundingEvent]:
        events: list[FundingEvent] = []
        for pos in positions:
            if pos.product != "perp":
                continue
            if pos.qty_base == 0.0:
                continue
            df = funding_data.get((pos.venue, pos.symbol))
            if df is None:
                continue
            match = df.filter(pl.col("ts_ms") == ts_ms)
            if match.height == 0:
                continue
            rate = float(match["realized"][0])
            mark_px = mark_pxs.get((pos.venue, pos.symbol, "perp"))
            if mark_px is None:
                continue
            notional = abs(pos.qty_base) * mark_px
            sign = 1.0 if pos.qty_base > 0 else -1.0
            payment = -sign * notional * rate
            events.append(
                FundingEvent(
                    ts_ms=ts_ms,
                    venue=pos.venue,
                    symbol=pos.symbol,
                    position_qty=pos.qty_base,
                    funding_rate=rate,
                    mark_px=mark_px,
                    payment_quote=payment,
                )
            )
        return events
