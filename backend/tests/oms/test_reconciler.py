"""Tests for PositionReconciler — book vs exchange + hedge consistency drift."""

from __future__ import annotations

import pytest

from app.backtest.state import Position
from app.exchanges.types import ExchangePosition
from app.oms.exceptions import HedgeDriftHalt, ReconciliationDriftHalt
from app.oms.reconciler import PositionReconciler
from app.profile.params import ProfileParams


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def _book_pos(qty: float, product: str = "spot", symbol: str = "BTCUSDT") -> Position:
    return Position(
        venue="binance",
        symbol=symbol,
        product=product,  # type: ignore[arg-type]
        qty_base=qty,
        avg_entry_px=60000.0,
    )


def _exchange_pos(qty: float, product: str = "spot", symbol: str = "BTCUSDT") -> ExchangePosition:
    return ExchangePosition(
        venue="binance",
        symbol=symbol,
        product=product,  # type: ignore[arg-type]
        qty_base=qty,
        avg_entry_px=60000.0,
        mark_px=60000.0,
        unrealized_pnl_quote=0.0,
    )


def test_no_drift_ok() -> None:
    r = PositionReconciler(params=_params())
    r.check_book_vs_exchange(
        book_positions=(_book_pos(0.1),),
        exchange_positions=(_exchange_pos(0.1),),
    )  # no raise


def test_book_drift_under_threshold_ok() -> None:
    r = PositionReconciler(params=_params())
    # 1% drift on a 0.1 position: 0.001 difference; threshold is 2%
    r.check_book_vs_exchange(
        book_positions=(_book_pos(0.1),),
        exchange_positions=(_exchange_pos(0.101),),
    )


def test_book_drift_over_threshold_raises() -> None:
    r = PositionReconciler(params=_params())
    # 5% drift on a 0.1 position: 0.005 difference; threshold is 2%
    with pytest.raises(ReconciliationDriftHalt):
        r.check_book_vs_exchange(
            book_positions=(_book_pos(0.1),),
            exchange_positions=(_exchange_pos(0.105),),
        )


def test_cold_start_empty_book_is_ok() -> None:
    r = PositionReconciler(params=_params())
    # Empty book + exchange has a position → cold start, no halt
    r.check_book_vs_exchange(
        book_positions=(),
        exchange_positions=(_exchange_pos(0.1),),
    )


def test_hedge_consistency_no_drift() -> None:
    r = PositionReconciler(params=_params())
    r.check_hedge_consistency(
        positions=(_book_pos(0.1, "spot"), _book_pos(-0.1, "perp")),
    )


def test_hedge_consistency_drift_over_threshold_raises() -> None:
    r = PositionReconciler(params=_params())
    # 10% drift: spot 0.1, perp -0.11; threshold 5%
    with pytest.raises(HedgeDriftHalt):
        r.check_hedge_consistency(
            positions=(_book_pos(0.1, "spot"), _book_pos(-0.11, "perp")),
        )


def test_hedge_consistency_no_perp_pair_is_ok() -> None:
    r = PositionReconciler(params=_params())
    # Only spot → not a hedge pair, no check
    r.check_hedge_consistency(
        positions=(_book_pos(0.1, "spot"),),
    )
