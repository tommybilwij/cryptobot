"""Backtest validator strategies — used to prove the engine plumbing.

Real strategies (funding arb, factor portfolio) ship in Phase 6+ under
``app.strategies/``. These are *engine validators*: minimal, deterministic,
designed to exercise specific engine features (P&L accumulation, hedge
pairs, funding accounting).
"""
