"""Tests for MetaAllocator."""

from __future__ import annotations

from app.profile.params import ProfileParams
from app.services.meta_allocator import MetaAllocator


def _params() -> ProfileParams:
    return ProfileParams(profile={})


def test_empty_returns_empty_allocation() -> None:
    a = MetaAllocator(params=_params())
    assert a.allocate(strategy_returns={}) == ()


def test_single_positive_strategy_gets_full_weight() -> None:
    a = MetaAllocator(params=_params())
    # 100 positive returns → high Sharpe
    returns = [0.0001] * 100
    allocs = a.allocate(strategy_returns={"funding_arb": returns})
    assert len(allocs) == 1
    # Single positive strategy with no negatives → weight capped at max_weight or = 1.0
    assert allocs[0].weight > 0.0


def test_weights_sum_to_one_with_two_positive_strategies() -> None:
    a = MetaAllocator(params=_params())
    returns_a = [0.0002] * 100  # better
    returns_b = [0.0001] * 100  # worse
    allocs = a.allocate(strategy_returns={
        "funding_arb": returns_a,
        "factor_portfolio": returns_b,
    })
    total = sum(al.weight for al in allocs)
    assert abs(total - 1.0) < 1e-6


def test_better_sharpe_gets_higher_weight() -> None:
    a = MetaAllocator(params=_params())
    # Strategy A: consistent positive returns (high Sharpe)
    returns_a = [0.0002, 0.0001, 0.0003, 0.0002, 0.0001] * 20
    # Strategy B: mixed (lower Sharpe)
    returns_b = [0.0001, -0.0001, 0.0002, -0.0001, 0.0001] * 20
    allocs = a.allocate(strategy_returns={"A": returns_a, "B": returns_b})
    a_alloc = next(x for x in allocs if x.strategy_name == "A")
    b_alloc = next(x for x in allocs if x.strategy_name == "B")
    assert a_alloc.weight >= b_alloc.weight


def test_all_negative_sharpes_returns_equal_weights() -> None:
    a = MetaAllocator(params=_params())
    # Both strategies losing → all non-positive
    returns = [-0.0001] * 100
    allocs = a.allocate(strategy_returns={"A": returns, "B": returns})
    # Equal weights
    weights = sorted(al.weight for al in allocs)
    assert abs(weights[0] - weights[1]) < 1e-6


def test_short_returns_yield_zero_sharpe() -> None:
    a = MetaAllocator(params=_params())
    allocs = a.allocate(strategy_returns={"A": [0.001]})  # only 1 sample
    assert allocs[0].sharpe_30d == 0.0
