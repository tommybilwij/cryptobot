# Cryptobot Hardening Pass 4 — OMS Robustness

**Date**: 2026-05-24

## Goal

Two robustness fixes in the OMS dispatch path:
1. **Partial-fill aggregation** — currently partial fills are logged but the unfilled remainder is dropped. OMS should track and requeue.
2. **Hedge auto-rebalance** — currently `HedgeDriftHalt` only halts. Add an opt-in path that emits closing orders for the over-sized leg before halting.

## Architecture

### Partial-fill tracking

`OMS.dispatch` checks `status.status == "partially_filled"`. When detected:
- Records the partial `Fill(qty_base=status.filled_qty_base)`
- Computes `remainder_qty = order.qty_base - status.filled_qty_base`
- If remainder > registry threshold `oms.partial_fill_min_remainder_qty` (default 0.0001), emit a new market order for the remainder same tick
- Caps retries at `oms.max_partial_fill_retries` (default 3)
- Tracks in audit's `fills` JSONB

### Hedge auto-rebalance

New profile flag `oms.hedge_auto_rebalance_enabled: bool = False` (registry default off).
When `True` and `PositionReconciler.check_hedge_consistency` would raise, instead:
- Compute `|spot_qty| - |perp_qty|` and which leg is bigger
- Emit a closing order for the over-sized leg
- Audit records the rebalance as a special `reconciliation_status="auto_rebalance"`

Stays opt-in because auto-trading on detected drift is risky; default behaviour (halt) remains the safe path.

## Components

- `backend/app/oms/service.py` — partial-fill loop + auto-rebalance branch
- `backend/app/profile/defaults.py` — 3 new keys (`oms.partial_fill_min_remainder_qty`, `oms.max_partial_fill_retries`, `oms.hedge_auto_rebalance_enabled`)
- `backend/tests/oms/test_dispatch.py` — append 2 tests
- `backend/tests/oms/test_reconciler.py` — append 1 test for auto-rebalance branch

## DoD

~317 tests pass. Partial fills get requeued. Auto-rebalance opt-in behaviour works.
