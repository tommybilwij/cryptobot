"""Engine — event loop walking MarketSnapshots from BacktestLoader.

Order at each tick:
  1. apply funding payments (if any perp positions held)
  2. call strategy.evaluate(state, params)
  3. apply fills (best-effort; downsize once on InsufficientCashError, then skip)
  4. mark-to-market → append point on equity curve

Note on the downsize-and-retry: strategies size against a notional that does
not know about slippage and fees, so a "spend everything" order will exceed
cash by ~slip_bps + fee_bps. The engine retries that order list once with
a small safety shrink so the canonical "buy and hold all of it" pattern
works in backtest. Production sizing should reserve its own buffer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

import polars as pl

from app.backtest.fills import FillSimulator, InsufficientCashError
from app.backtest.funding import FundingLedger
from app.backtest.loader import BacktestLoader
from app.backtest.orders import Order
from app.backtest.positions import PositionBook
from app.backtest.state import MarketState, Product
from app.backtest.strategies.base import Strategy
from app.profile.params import ProfileParams

# Single retry on InsufficientCashError: shrink every order by this factor.
# Sized to cover typical exchange slippage (5-8 bps) + fees (4-10 bps) with
# headroom; one retry only — if still short, skip the whole batch.
_CASH_RETRY_SHRINK = 0.99


@dataclass
class BacktestResult:
    equity_curve: pl.DataFrame  # ts_ms / equity / cash / num_open_positions
    num_trades: int


class Engine:
    def __init__(
        self,
        *,
        loader: BacktestLoader,
        strategy: Strategy,
        params: ProfileParams,
    ) -> None:
        self._loader = loader
        self._strategy = strategy
        self._params = params

    def run(
        self,
        *,
        venue: str,
        symbols: list[str],
        products: list[Product],
        start: datetime,
        end: datetime,
    ) -> BacktestResult:
        cash: float = float(self._params.get("backtest.initial_cash_quote_usdc"))
        book = PositionBook()
        fill_sim = FillSimulator(params=self._params)
        funding = FundingLedger()

        # preload funding data per (venue, symbol)
        funding_data: dict[tuple[str, str], pl.DataFrame] = {}
        for symbol in symbols:
            df = self._loader.load_funding(
                venue=venue, symbol=symbol, start=start, end=end
            )
            if df is not None and df.height > 0:
                funding_data[(venue, symbol)] = df

        rows_ts: list[int] = []
        rows_equity: list[float] = []
        rows_cash: list[float] = []
        rows_open: list[int] = []
        num_trades = 0

        for snapshot in self._loader.iter_snapshots(
            venue=venue, symbols=symbols, products=products, start=start, end=end
        ):
            # 1) funding for any open perp positions at this ts
            mark_pxs: dict[tuple[str, str, str], float] = {
                (k[0], k[1], k[2]): bar.close for k, bar in snapshot.bars.items()
            }
            events = funding.events_for(
                positions=book.snapshot(),
                ts_ms=snapshot.ts_ms,
                funding_data=funding_data,
                mark_pxs=mark_pxs,
            )
            for event in events:
                cash += event.payment_quote

            # 2) build state, call strategy
            state = MarketState(
                snapshot=snapshot,
                positions=book.snapshot(),
                cash_quote=cash,
            )
            orders = self._strategy.evaluate(state, self._params)

            # 3) apply fills (best-effort; one shrink-and-retry on cash error)
            if orders:
                try:
                    fills, cash = fill_sim.fill(orders, snapshot, cash=cash)
                    book.apply(fills)
                    num_trades += len(fills)
                except InsufficientCashError:
                    shrunk = [_shrink(o, _CASH_RETRY_SHRINK) for o in orders]
                    try:
                        fills, cash = fill_sim.fill(shrunk, snapshot, cash=cash)
                        book.apply(fills)
                        num_trades += len(fills)
                    except InsufficientCashError:
                        pass

            # 4) mark-to-market → record equity-curve row
            mtm = book.mark_to_market(snapshot)
            equity = cash + mtm
            rows_ts.append(snapshot.ts_ms)
            rows_equity.append(equity)
            rows_cash.append(cash)
            rows_open.append(len(book.snapshot()))

        equity_curve = pl.DataFrame(
            {
                "ts_ms": rows_ts,
                "equity": rows_equity,
                "cash": rows_cash,
                "num_open_positions": rows_open,
            }
        )
        return BacktestResult(equity_curve=equity_curve, num_trades=num_trades)


def _shrink(order: Order, factor: float) -> Order:
    """Return a copy of `order` with qty_base scaled by `factor`."""
    return replace(order, qty_base=order.qty_base * factor)
