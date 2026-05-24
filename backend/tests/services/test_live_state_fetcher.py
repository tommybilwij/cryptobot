"""Tests for LiveStateFetcher."""

from __future__ import annotations

import pytest

from app.exchanges.paper import PaperExchange
from app.profile.params import ProfileParams
from app.services.live_state_fetcher import LiveStateFetcher


def _params() -> ProfileParams:
    return ProfileParams(profile={})


@pytest.mark.asyncio
async def test_fetches_market_state_with_balance_positions_and_funding() -> None:
    paper = PaperExchange(venue="binance", params=_params(), initial_cash=10_000.0)
    paper.set_mark_price("BTCUSDT", "spot", 60_000.0)
    paper.set_mark_price("BTCUSDT", "perp", 60_010.0)
    paper.set_funding_rate("BTCUSDT", 0.0002)

    fetcher = LiveStateFetcher(exchanges={"binance": paper}, venue="binance")
    state = await fetcher.fetch_market_state(symbols=["BTCUSDT"])

    assert state.cash_quote == 10_000.0
    assert state.positions == ()
    assert state.snapshot.funding_rates[("binance", "BTCUSDT")] == 0.0002
    assert state.snapshot.bars[("binance", "BTCUSDT", "spot")].close == 60_000.0
    assert state.snapshot.bars[("binance", "BTCUSDT", "perp")].close == 60_010.0
